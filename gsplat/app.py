"""Phone video -> clean object-only Gaussian splat on a Modal GPU.

    modal run app.py --video orbit.mp4                      # full run (~28 s warm) -> out/<video stem>/
    modal run app.py --video orbit.mp4 --stop-after masks   # iterate on one stage
    modal run app.py --video orbit.mp4 --video2 orbit_reverse.mp4 --name merged   # top + flipped bottom

For the demo use the deployed app instead (no cold start): see client.py.

Outputs land in out/<name>/: splat.spz (~3 MB) plus debug media and run.json (--ply adds a ~39 MB .ply, for local inspection only).
--gpu H100 roughly halves the pose stage; --scale sets the training resolution (default: auto from a pixel budget; 1.0 = full video resolution).
"""
import json
import os
import sys
import time
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root: shared `supabase_setup` package

CUDA_ARCHS = "8.0;8.6;8.9;9.0"


def _has_supabase() -> bool:
    """Whether the `mint-supabase` secret exists. Only storage mode (run_scan) needs it, so dev runs and
    deploys still work before it is created. Decided once where the app is defined (locally) and baked
    into the image env, so the container sees the same answer: re-checking in the container would
    change the function's dependency count and break start-up. Redeploy after creating the secret."""
    if not modal.is_local():
        return os.environ.get("MINT_SUPABASE") == "1"
    try:
        modal.Secret.from_name("mint-supabase").hydrate()
        return True
    except modal.exception.NotFoundError:
        print("note: Modal secret `mint-supabase` not found: storage mode (run_scan) disabled", file=sys.stderr)
        return False


HAS_SUPABASE = _has_supabase()

# The first layers match the legacy image exactly so Modal reuses the cached build
# (the gsplat CUDA compile takes minutes). Add new layers at the end.
image = (
    modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.10")
    .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0", "build-essential", "ninja-build", "clang")
    .pip_install("torch==2.4.0", "torchvision==0.19.0", index_url="https://download.pytorch.org/whl/cu124")
    .pip_install("numpy<2", "scipy", "plyfile", "einops", "safetensors", "huggingface_hub",
                 "Pillow", "opencv-python-headless", "ultralytics")
    .pip_install("gsplat", extra_index_url="https://docs.gsplat.studio/whl/pt24cu124")
    .run_commands("git clone --depth 1 https://github.com/facebookresearch/vggt /opt/vggt")
    .env({
        "PYTHONPATH": "/opt/vggt",
        "TORCH_CUDA_ARCH_LIST": CUDA_ARCHS,
        "HF_HOME": "/models/hf",
        "YOLO_AUTOINSTALL": "False",
    })
    .run_commands('python -c "from gsplat.cuda._backend import _C; print(\'gsplat backend:\', _C)"')
    # --- new layers
    .pip_install("hydra-core>=1.3.2", "iopath>=0.1.10", "tqdm", "wheel", "setuptools>=61")
    # SAM 2's build pins a newer torch; build against the installed one, skip its optional CUDA op
    .run_commands("SAM2_BUILD_CUDA=0 pip install --no-deps --no-build-isolation "
                  "'git+https://github.com/facebookresearch/sam2.git'")
    # Niantic's reference SPZ writer (pinned); builds its C++ core with CMake
    .pip_install("cmake>=3.24", "ninja")
    .apt_install("zlib1g-dev")
    .run_commands("pip install 'spz @ git+https://github.com/nianticlabs/spz.git@affd0ecea7fbb4c265ee119475af7ee5b2997482'")
    .env({"MINT_SUPABASE": "1" if HAS_SUPABASE else "0"})
    .add_local_python_source("mintsplat", "supabase_setup")
)

app = modal.App("mint-gsplat", image=image)
models_vol = modal.Volume.from_name("mint-models", create_if_missing=True)
SECRETS = ([modal.Secret.from_name("mint-supabase", required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])]
           if HAS_SUPABASE else [])
@app.cls(gpu="L40S", cpu=8.0, memory=32768, volumes={"/models": models_vol},
         secrets=SECRETS, timeout=900, scaledown_window=300)
class Splatter:
    @modal.enter()
    def load(self):
        import torch
        from vggt.models.vggt import VGGT

        from mintsplat.masks import Segmenter

        t0 = time.time()
        self.segmenter = Segmenter()
        self.vggt = VGGT.from_pretrained("facebook/VGGT-1B").eval().cuda()
        try:
            models_vol.commit()
        except Exception as e:  # weight cache is a nicety
            print("volume commit skipped:", e)
        torch.cuda.synchronize()
        print(f"[time] model_load: {time.time() - t0:.1f}s (cold start only)", flush=True)

    @modal.method()
    def run(self, video: bytes | list[bytes], cfg: dict) -> dict:
        """One mp4, or [upright orbit, flipped-over orbit] to merge into one splat."""
        from mintsplat.pipeline import run

        return run(self, video, cfg)

    @modal.method()
    def run_scan(self, scan_id: str, batch_id: str | None = None, cfg: dict | None = None) -> dict:
        """Storage mode. Reads scans/{scan_id}/top.* (+ bottom.* if present) from Supabase, writes
        assets/splats/{scan_id}.spz + .json (manifest), assets/views/{scan_id}/ (8 reference views + views.json),
        refreshes assets/splats/index.json (newest first; what listing/ingest.py polls without a key), and
        broadcasts `stage` / `passport_ready`        on Realtime channel batch:{batch_id}. mint-api calls this with .spawn() after upload."""
        from mintsplat.pipeline import run
        from mintsplat.publish import fetch_inputs, publish
        from supabase_setup.storage import Events, Supabase

        if not HAS_SUPABASE:
            raise RuntimeError("storage mode needs the Modal secret `mint-supabase`; create it, then redeploy")
        sb = Supabase()
        batch_id = batch_id or scan_id
        ev = Events(sb, batch_id)
        try:
            keys, videos, io = fetch_inputs(sb, scan_id)
            res = run(self, videos if len(videos) > 1 else videos[0],
                      {**(cfg or {}), "ply": False, "debug": False, "views": True}, on_event=ev.stage_hook(scan_id))
            manifest = publish(sb, scan_id, batch_id, keys, res, io)
            ev.send("passport_ready", manifest)
            return manifest
        except Exception as e:
            ev.send("error", {"stage": "splat", "message": str(e)[:300], "scan_id": scan_id})
            raise
        finally:
            ev.close()


@app.local_entrypoint()
def main(video: str, video2: str = "", name: str = "", n_frames: int = 80, stop_after: str = "", iters: int = 1000,
         batch: int = 4, cap: int = 200_000, scale: float = 0.0,
         debug: bool = True, ply: bool = False, spz_sweep: bool = False, gpu: str = "", box_refine: bool = True, app_lr: float = 0.0, sh: int = 3, train_json: str = ""):
    src = Path(video)
    out_dir = Path("out") / (name or src.stem)
    cfg = {"n_frames": n_frames, "stop_after": stop_after or None, "debug": debug, "ply": ply, "spz_sweep": spz_sweep, "box_refine": box_refine,
           "train": {"iters": iters, "batch": batch, "cap_max": cap, "train_scale": scale or None,
                     "appearance_lr": app_lr, "sh_degree": sh, **json.loads(train_json or "{}")}}

    t0 = time.perf_counter()
    payload = [src.read_bytes(), Path(video2).read_bytes()] if video2 else src.read_bytes()
    cls = Splatter.with_options(gpu=gpu) if gpu else Splatter  # e.g. --gpu H100 to compare
    res = cls().run.remote(payload, cfg)
    from client import save

    save(res, out_dir, time.perf_counter() - t0)
