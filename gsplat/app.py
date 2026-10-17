"""Phone video -> clean object-only Gaussian splat on a Modal GPU.

    modal run app.py --video orbit.mp4                      # full run (~28 s warm) -> out/<video stem>/
    modal run app.py --video orbit.mp4 --stop-after masks   # iterate on one stage
    modal run app.py --video orbit.mp4 --video2 orbit_reverse.mp4 --name merged   # top + flipped bottom

For the demo use the deployed app instead (no cold start): see client.py.

Outputs land in out/<name>/: splat.spz (~3 MB; add --ply for the ~39 MB .ply) plus debug media and run.json.
--gpu H100 roughly halves the pose stage; --scale 1.0 trains at full video resolution (sharpest).
"""
import json
import sys
import time
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root: shared `supabase_setup` package

CUDA_ARCHS = "8.0;8.6;8.9;9.0"

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
    .add_local_python_source("mintsplat", "supabase_setup")
)

app = modal.App("mint-gsplat", image=image)
models_vol = modal.Volume.from_name("mint-models", create_if_missing=True)
work_vol = modal.Volume.from_name("mint-work", create_if_missing=True)  # GPU-side hand-off to B (.ply etc.)
supabase = modal.Secret.from_name("mint-supabase", required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])


@app.cls(gpu="L40S", cpu=8.0, memory=32768, volumes={"/models": models_vol, "/work": work_vol},
         secrets=[supabase], timeout=900, scaledown_window=300)
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
        assets/splats/{scan_id}.spz + .json, assets/views/{scan_id}/ (8 cube-corner PNGs + views.json),
        /work/{scan_id}/splat.ply (Volume mint-work, for B), and broadcasts `stage` / `passport_ready`
        on Realtime channel batch:{batch_id}. mint-api calls this with .spawn() after upload."""
        from concurrent.futures import ThreadPoolExecutor

        from mintsplat.pipeline import run
        from supabase_setup.storage import ASSETS, SCANS, Events, Supabase

        sb = Supabase()
        batch_id = batch_id or scan_id
        ev = Events(sb, batch_id)
        io = {}
        try:
            t0 = time.perf_counter()
            names = sb.list(SCANS, scan_id)
            pick = lambda role: next((n for n in sorted(names) if n.startswith(role + ".")), None)
            keys = [k for k in (pick("top"), pick("bottom")) if k]
            if not keys or not keys[0].startswith("top."):
                raise FileNotFoundError(f"no scans/{scan_id}/top.* uploaded (found {names})")
            with ThreadPoolExecutor(2) as ex:
                videos = list(ex.map(lambda k: sb.download(SCANS, f"{scan_id}/{k}"), keys))
            io["download_s"] = round(time.perf_counter() - t0, 2)
            io["download_mb"] = round(sum(map(len, videos)) / 1e6, 1)

            res = run(self, videos if len(videos) > 1 else videos[0],
                      {**(cfg or {}), "ply": True, "debug": False, "cube_views": True}, on_event=ev.stage_hook(scan_id))
            files = res.pop("files")

            t0 = time.perf_counter()
            Path(f"/work/{scan_id}").mkdir(parents=True, exist_ok=True)
            Path(f"/work/{scan_id}/splat.ply").write_bytes(files.pop("splat.ply"))
            Path(f"/work/{scan_id}/views.json").write_bytes(files["cube/views.json"])
            work_vol.commit()
            io["ply_to_volume_s"] = round(time.perf_counter() - t0, 2)

            t0 = time.perf_counter()
            targets = [(f"splats/{scan_id}.spz", files.pop("splat.spz"), "application/octet-stream")]
            targets += [(f"views/{scan_id}/{k.split('/', 1)[1]}", v,
                         "application/json" if k.endswith(".json") else "image/png") for k, v in files.items()]
            with ThreadPoolExecutor(8) as ex:
                urls = dict(zip([p for p, _, _ in targets],
                                ex.map(lambda x: sb.upload(ASSETS, *x), targets)))
            io["upload_s"] = round(time.perf_counter() - t0, 2)
            io["upload_mb"] = round(sum(len(d) for _, d, _ in targets) / 1e6, 2)

            manifest = {
                "v": 3, "scan_id": scan_id, "batch_id": batch_id, "inputs": [f"{SCANS}/{scan_id}/{k}" for k in keys],
                "splat_path": f"{ASSETS}/splats/{scan_id}.spz", "splat_url": urls[f"splats/{scan_id}.spz"],
                "splat_ply_path": f"mint-work/{scan_id}/splat.ply",
                "views_json_url": urls[f"views/{scan_id}/views.json"],
                "views": {p.rsplit("/", 1)[1].removesuffix(".png"): u for p, u in urls.items() if p.endswith(".png")},
                "metric_scale": None,  # video-only scans are not metric yet
                "frame": "scan frame: +Y up, origin on the support plane under the object, right-handed (RUB)",
                "gaussians": res["gaussians"]["after"], "sizes_mb": res["sizes_mb"],
                "stage_timings_ms": {k: int(v * 1000) for k, v in res["timings"].items()},
                "register": res.get("register"), "io": io,
            }
            sb.upload(ASSETS, f"splats/{scan_id}.json", json.dumps(manifest, indent=1).encode(), "application/json")
            ev.send("passport_ready", manifest)
            return manifest
        except Exception as e:
            ev.send("error", {"stage": "splat", "message": str(e)[:300], "scan_id": scan_id})
            raise
        finally:
            ev.close()


@app.local_entrypoint()
def main(video: str, video2: str = "", name: str = "", n_frames: int = 80, stop_after: str = "", iters: int = 1000,
         batch: int = 4, cap: int = 200_000, scale: float = 0.75,
         debug: bool = True, ply: bool = False, spz_sweep: bool = False, gpu: str = "", app_lr: float = 0.0, sh: int = 3, train_json: str = ""):
    src = Path(video)
    out_dir = Path("out") / (name or src.stem)
    cfg = {"n_frames": n_frames, "stop_after": stop_after or None, "debug": debug, "ply": ply, "spz_sweep": spz_sweep,
           "train": {"iters": iters, "batch": batch, "cap_max": cap, "train_scale": scale,
                     "appearance_lr": app_lr, "sh_degree": sh, **json.loads(train_json or "{}")}}

    t0 = time.perf_counter()
    payload = [src.read_bytes(), Path(video2).read_bytes()] if video2 else src.read_bytes()
    cls = Splatter.with_options(gpu=gpu) if gpu else Splatter  # e.g. --gpu H100 to compare
    res = cls().run.remote(payload, cfg)
    from client import save

    save(res, out_dir, time.perf_counter() - t0)
