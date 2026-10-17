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


def _has_secret(name: str, env: str, what: str) -> bool:
    """Whether a Modal secret exists. Only storage mode needs `mint-supabase` (and the listing step `mint-listing`),
    so dev runs and deploys still work before they are created. Decided once where the app is defined (locally) and
    baked into the image env, so the container sees the same answer: re-checking in the container would change the
    function's dependency count and break start-up. Redeploy after creating a secret."""
    if not modal.is_local():
        return os.environ.get(env) == "1"
    try:
        modal.Secret.from_name(name).hydrate()
        return True
    except modal.exception.NotFoundError:
        print(f"note: Modal secret `{name}` not found: {what} disabled", file=sys.stderr)
        return False


HAS_SUPABASE = _has_secret("mint-supabase", "MINT_SUPABASE", "storage mode (run_scan, on_upload)")
HAS_LISTING = _has_secret("mint-listing", "MINT_LISTING", "the listing step after the splat (Jev + Gemini)")
LISTING_DIR = Path(__file__).resolve().parent.parent / "listing"
LIVE_GPU = "H100"  # scans started by the upload webhook
PREWARM_ON = {"session.json", "bottom.mp4"}  # a scan has started: get a GPU container ready before video.mp4
FLAGS = {"MINT_SUPABASE": "1" if HAS_SUPABASE else "0", "MINT_LISTING": "1" if HAS_LISTING else "0"}

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
    # listing/ (Jev + Gemini) runs in this container after the splat; numpy stays < 2 for the stack above
    .pip_install("numpy<2", "typesafe-sdk==0.7.5", "google-genai>=1.0", "pydantic>=2.7,<3", "python-dotenv>=1.0",
                 "httpx>=0.27")
    .env(FLAGS)
    .add_local_python_source("mintsplat", "supabase_setup")
    .add_local_dir(LISTING_DIR, "/listing", ignore=[".env", ".venv", "runs", "samples", "demo_cache", "fixtures",
                                                    "tests", "scripts", "**/__pycache__", ".pytest_cache"])
)

app = modal.App("mint-gsplat", image=image)
models_vol = modal.Volume.from_name("mint-models", create_if_missing=True)
SECRETS = ([modal.Secret.from_name("mint-supabase", required_keys=["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"])]
           if HAS_SUPABASE else [])
LISTING_SECRETS = ([modal.Secret.from_name("mint-listing", required_keys=["TYPESAFE_API_KEY", "GEMINI_API_KEY",
                                                                           "SERPER_API_KEY"])]
                   if HAS_LISTING else [])
jobs = modal.Dict.from_name("mint-scan-jobs", create_if_missing=True)  # scan_id -> claimed at, so each runs once


@app.cls(gpu="L40S", cpu=8.0, memory=32768, volumes={"/models": models_vol},
         secrets=SECRETS + LISTING_SECRETS, timeout=900, scaledown_window=300)
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
        refreshes assets/splats/index.json (newest first; what listing/ingest.py polls without a key), then runs
        the listing pipeline (listing/, Jev + Gemini) and publishes assets/listings/{scan_id}.json + index.json for
        the website. Broadcasts `stage` / `passport_ready` / `listing_ready` on Realtime channel batch:{batch_id}.
        Started by on_upload (the Supabase webhook) when the phone's video lands; cfg {"listing": False} skips it."""
        from mintsplat.market import list_scan
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
                      {**(cfg or {}), "ply": False, "debug": False, "views": True, "rotate_cw": io["rotate_cw"]},
                      on_event=ev.stage_hook(scan_id))
            manifest = publish(sb, scan_id, batch_id, keys, res, io)
            ev.send("passport_ready", manifest)
            if HAS_LISTING and (cfg or {}).get("listing", True):
                ev.send("stage", {"scan_id": scan_id, "stage": "7_listing", "status": "started", "ms": 0})
                # the product name the seller typed on the dashboard lets listing/ search for a reference photo
                title = (cfg or {}).get("seller_name") or (io.get("session") or {}).get("title")
                doc = list_scan(sb, scan_id, manifest, res["files"]["splat.spz"], {**(cfg or {}), "seller_name": title})
                ev.send("stage", {"scan_id": scan_id, "stage": "7_listing", "status": doc["status"],
                                  "ms": doc.get("timings_ms", {}).get("listing_pipeline", 0)})
                ev.send("listing_ready" if doc["status"] == "listed" else f"listing_{doc['status']}", doc)
                manifest = {**manifest, "listing": doc}
            return manifest
        except Exception as e:
            ev.send("error", {"stage": "splat", "message": str(e)[:300], "scan_id": scan_id})
            raise
        finally:
            ev.close()

    @modal.method()
    def prewarm(self) -> str:
        """on_upload calls this as soon as a scan starts (session.json, bottom.mp4), so the cold start happens while
        the seller is still recording. Loading the models is not all of it: the first real job on a container also
        pays ~8 s for CUDA loading kernels lazily (measured: SAM 2, VGGT, registration and training each slower the
        first time). So, once per container, run one tiny real job on the newest published scan (12 frames per
        video, 60 steps, nothing published)."""
        if getattr(self, "_warm", False) or not HAS_SUPABASE:
            return "warm"
        self._warm = True
        try:
            from mintsplat.pipeline import run
            from mintsplat.publish import fetch_inputs
            from supabase_setup.storage import ASSETS, Supabase

            sb = Supabase()
            scans = json.loads(sb.download(ASSETS, "splats/index.json")).get("scans", [])
            if scans:
                t0 = time.time()
                _, videos, io = fetch_inputs(sb, scans[0]["scan_id"])
                run(self, videos if len(videos) > 1 else videos[0], {"n_frames": 12, "debug": False, "views": False,
                                                                    "rotate_cw": io["rotate_cw"], "train": {"iters": 60}})
                print(f"[time] warm_up: {time.time() - t0:.1f}s", flush=True)
        except Exception as e:  # a warm-up must never break anything
            print(f"warm-up skipped: {e}", flush=True)
        return "warm"

    @modal.method()
    def relist(self, scan_id: str, seller_name: str | None = None) -> dict:
        """Run only the listing step again on a published splat (after a Gemini/Jev outage, or with a product name),
        and republish assets/listings/{scan_id}.json."""
        from mintsplat.market import list_scan
        from supabase_setup.storage import ASSETS, Supabase

        sb = Supabase()
        manifest = json.loads(sb.download(ASSETS, f"splats/{scan_id}.json"))
        session = (manifest.get("io") or {}).get("session") or {}
        return list_scan(sb, scan_id, manifest, sb.download(ASSETS, f"splats/{scan_id}.spz"),
                         {"seller_name": seller_name or session.get("title")})


hook_image = (modal.Image.debian_slim(python_version="3.11").pip_install("fastapi[standard]").env(FLAGS)
              .add_local_python_source("supabase_setup"))


@app.function(image=hook_image, secrets=SECRETS, timeout=60)
@modal.fastapi_endpoint(method="POST")
def on_upload(body: dict) -> dict:
    """Supabase webhook (supabase_setup/webhook.sql): a file landed in Storage. For scans/{uuid}/video.mp4 (what the
    iOS app uploads last) it starts Splatter.run_scan on an H100 and returns at once. Earlier files of the same scan
    (session.json when the scan is requested or picked up, bottom.mp4) only warm a container up, once per scan.
    The URL is public, so it only acts on a video that really is in the bucket, and only once per scan
    (Dict `mint-scan-jobs`)."""
    import re

    from supabase_setup.storage import SCANS, Supabase

    rec = body.get("record") or body  # a Database Webhook payload, or {bucket_id, name} from the trigger
    bucket, name = rec.get("bucket_id"), str(rec.get("name") or "")
    scan_id, _, file = name.partition("/")
    uuid = r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    if bucket != SCANS or not re.fullmatch(uuid, scan_id):
        return {"ok": True, "ignored": f"{bucket}/{name}"}
    splatter = modal.Cls.from_name("mint-gsplat", "Splatter").with_options(gpu=LIVE_GPU)
    if file != "video.mp4":
        if file in PREWARM_ON and jobs.put(f"prewarm:{scan_id}", time.time(), skip_if_exists=True):
            splatter().prewarm.spawn()
            return {"ok": True, "prewarm": scan_id}
        return {"ok": True, "ignored": f"{bucket}/{name}"}
    if not HAS_SUPABASE:
        return {"ok": False, "error": "Modal secret mint-supabase missing; create it and redeploy"}
    if file not in Supabase().list(SCANS, scan_id):
        return {"ok": False, "error": f"scans/{name} not found"}
    if not jobs.put(scan_id, time.time(), skip_if_exists=True):
        return {"ok": True, "duplicate": scan_id}
    call = splatter().run_scan.spawn(scan_id)
    return {"ok": True, "scan_id": scan_id, "call_id": call.object_id}


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
