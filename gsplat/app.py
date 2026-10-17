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
HAS_BUYER = _has_secret("mint-buyer", "MINT_BUYER", "the buyer's rescan check (multiagent/buyer_agent)")
MULTIAGENT_DIR = Path(__file__).resolve().parent.parent / "multiagent"
LISTING_DIR = Path(__file__).resolve().parent.parent / "listing"
LIVE_GPU = "H100"  # scans started by the upload webhook
PREWARM_ON = {"session.json", "bottom.mp4"}  # a scan has started: get a GPU container ready before video.mp4
FLAGS = {"MINT_SUPABASE": "1" if HAS_SUPABASE else "0", "MINT_LISTING": "1" if HAS_LISTING else "0",
         "MINT_BUYER": "1" if HAS_BUYER else "0"}

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
BUYER_SECRETS = ([modal.Secret.from_name("mint-buyer", required_keys=["TYPESAFE_API_KEY", "GROQ_API_KEY",
                                                                       "BUYER_AGENT_TOKEN"])]
                 if HAS_BUYER else [])
jobs = modal.Dict.from_name("mint-scan-jobs", create_if_missing=True)  # scan_id -> claimed at, so each runs once

# The buyer agent (multiagent/buyer_agent, Abhinav) has its own stack (numpy 2), so it runs in its own container.
compare_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install_from_requirements(str(MULTIAGENT_DIR / "requirements.txt"))
    .env({**FLAGS, "DATA_ROOT": "/tmp/mint-compare", "BUYER_AGENT_LIVE": "1"})
    .add_local_dir(MULTIAGENT_DIR / "buyer_agent", "/root/buyer_agent", ignore=["**/__pycache__"])
)


@app.function(image=compare_image, secrets=BUYER_SECRETS, cpu=4.0, memory=8192, timeout=600)
def compare_scans(cid: str, listing_id: str, listing_ply: bytes, buyer_ply: bytes, listing: dict,
                  match_check: dict | None) -> dict:
    """The buyer agent on two splats, unchanged: it aligns them, renders matching views, asks Jev (and Groq for the
    listing's claims) and returns its CompareResponse. -> {"response": CompareResponse JSON, "pairs": {name: png}}."""
    import asyncio
    import os

    from buyer_agent import align as align_mod, quality, sources
    from buyer_agent.api import _default_clients
    from buyer_agent.config import load_settings
    from buyer_agent.listing_adapter import claims_from_listing
    from buyer_agent.models import AlignmentMetrics, CompareRequest, ListingMatchCheck, SplatRef
    from buyer_agent.pipeline import Deps, compare
    from buyer_agent.render import CpuPointRenderer
    from buyer_agent.runlog import RunLog

    def upright_resolve(req, settings, renderer):
        """sources.resolve, except that both splats come from our pipeline in the same +Y-up scan frame, so the
        aligner only turns the rescan about +Y (align upright=True): a top-only rescan of an item listed top and
        bottom was otherwise fitted upside down and judged "different"."""
        a, b = sources._load(settings.data_root, req.listing_splat), sources._load(settings.data_root, req.buyer_splat)
        issues = quality.precheck(a, b)
        if issues:
            return sources.Resolved([], None, "icp", tuple(issues))
        result = align_mod.align(a, b, upright=True)
        fit = {k: v for k, v in result["metrics"].items() if k in AlignmentMetrics.model_fields}
        metrics = AlignmentMetrics(**fit | {"scale": result["scale"]})
        return sources.Resolved(renderer.render(a, b, result["matrix"], result["crop"]), metrics, "icp")

    folder = Path(os.environ["DATA_ROOT"]) / cid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "listing.ply").write_bytes(listing_ply)
    (folder / "buyer.ply").write_bytes(buyer_ply)
    settings = load_settings()
    jev, groq = _default_clients(settings)
    deps = Deps(settings=settings, jev=jev, groq=groq, renderer=CpuPointRenderer(settings.render_max_points),
                runlog_factory=lambda rid: RunLog(settings.runs_root, rid), resolver=upright_resolve)
    req = CompareRequest(
        comparison_id=cid, listing_id=listing_id,
        listing_splat=SplatRef(path=f"{cid}/listing.ply", format="ply", up_axis="+y", scan_id=listing_id),
        buyer_splat=SplatRef(path=f"{cid}/buyer.ply", format="ply", up_axis="+y", scan_id=cid),
        claims=claims_from_listing(listing),
        listing_match_check=ListingMatchCheck(verdict=match_check["verdict"], reason=match_check["reason"][:300])
        if match_check and match_check.get("verdict") else None)
    resp = asyncio.run(compare(req, deps))
    run_dir = settings.runs_root / cid
    pairs = {p.name: p.read_bytes() for p in sorted(run_dir.glob("[ab]_*.png"))} if run_dir.is_dir() else {}
    return {"response": json.loads(resp.model_dump_json()), "pairs": pairs}


def _gpu_dead(e: BaseException | None = None) -> bool:
    """A CUDA error (e.g. a device-side assert) poisons the GPU context for the rest of the process: every later
    call on this container fails. True if `e` is one, or (no `e`) if the context is already broken."""
    if e is not None:
        return "CUDA error" in str(e) or "device-side assert" in str(e)
    import torch

    try:
        torch.cuda.synchronize()
        return False
    except RuntimeError:
        return True


def _replace_container(why: str) -> None:
    """Exit so Modal starts a fresh container and retries the input there (see `retries` below)."""
    print(f"GPU context is broken ({why}); exiting so the input is retried on a fresh container", flush=True)
    os._exit(1)


@app.cls(gpu="L40S", cpu=8.0, memory=32768, volumes={"/models": models_vol},
         secrets=SECRETS + LISTING_SECRETS, timeout=900, scaledown_window=300,
         retries=modal.Retries(max_retries=1, initial_delay=1.0))  # only crashes reach it: see run_scan
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
        if _gpu_dead():
            _replace_container("found broken before the scan")
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
            if _gpu_dead(e):  # not the scan's fault: retry it on a fresh GPU, and don't tell the page it failed
                _replace_container(str(e)[:120])
            # anything else would fail the same way again: report it and return (no retry)
            ev.send("error", {"stage": "splat", "message": str(e)[:300], "scan_id": scan_id})
            return {"scan_id": scan_id, "error": f"{type(e).__name__}: {e}"[:500]}
        finally:
            ev.close()

    @modal.method()
    def run_verify(self, cid: str) -> dict:
        """A buyer's verify rescan (mint://verify?id=<cid>&listing=<scan_id>): scans/{cid}/rescan.mp4 (+ rescan2.mp4)
        -> the buyer's splat (published as splats/{cid}, kept out of the listing index; the check page shows it)
        -> the buyer agent against the listing's splat -> assets/comparisons/{cid}.json (CompareResponse) and the view
        pairs as assets/comparisons/{cid[:8]}/a_NN.png / b_NN.png, which the check page polls for."""
        import torch

        from mintsplat import export as export_mod
        from mintsplat.pipeline import run
        from mintsplat.publish import fetch_inputs, publish
        from supabase_setup.storage import ASSETS, SCANS, Events, Supabase

        if _gpu_dead():
            _replace_container("found broken before the check")
        sb = Supabase()
        ev = Events(sb, cid)
        t0 = time.time()

        def put_result(resp: dict, pairs: dict) -> dict:
            folder = f"comparisons/{cid[:8]}"
            for name, png in pairs.items():
                sb.upload(ASSETS, f"{folder}/{name}", png, "image/png")
            sb.upload(ASSETS, f"comparisons/{cid}.json", json.dumps(resp, indent=1).encode(), "application/json",
                      cache_control="no-cache")
            return resp

        def failed(code: str, message: str) -> dict:  # the CompareResponse shape the check page reads
            return {"v": 1, "comparison_id": cid, "status": "failed", "verdict": None, "claims_available": False,
                    "claims_findings": [], "next_step": None, "explanation": None,
                    "error": {"code": code, "message": message[:300]}, "model_ids": {},
                    "timings_ms": {"total": int((time.time() - t0) * 1000)}, "run_id": cid}

        try:
            names = sb.list(SCANS, cid)
            meta = {}
            for name in ("rescan.capture.json", "session.json"):
                if name in names:
                    meta = {**json.loads(sb.download(SCANS, f"{cid}/{name}")), **meta}
            listing_id = meta.get("listing_scan_id")
            if not listing_id:
                return put_result(failed("INPUT_INVALID", "The rescan does not say which listing it checks."), {})
            if not HAS_BUYER:
                return put_result(failed("INTERNAL", "The comparison service has no keys (Modal secret mint-buyer)."), {})
            # Like for like: a pass one side has and the other doesn't (the underside) would read as a difference.
            listing_inputs = json.loads(sb.download(ASSETS, f"splats/{listing_id}.json")).get("inputs", [])
            listing_two_pass = any(p.rsplit("/", 1)[-1].startswith("bottom.") for p in listing_inputs)
            keys, videos, io = fetch_inputs(sb, cid, verify=True)
            if len(videos) > 1 and not listing_two_pass:  # the listing never saw the underside: drop the rescan's
                keys, videos, io["rotate_cw"] = keys[:1], videos[:1], io["rotate_cw"][:1]
            res = run(self, videos if len(videos) > 1 else videos[0],
                      {"ply": True, "debug": False, "views": True, "rotate_cw": io["rotate_cw"]},
                      on_event=ev.stage_hook(cid))
            publish(sb, cid, cid, keys, res, io, index=False)
            ev.send("stage", {"scan_id": cid, "stage": "7_listing", "status": "started", "ms": 0})
            if listing_two_pass and len(videos) == 1:  # the rescan has no underside: compare the listing's top lap
                spz = self._listing_top_spz(sb, listing_id)
            else:
                spz = sb.download(ASSETS, f"splats/{listing_id}.spz")
            params = export_mod.from_spz(spz)
            listing_ply = export_mod.to_ply(params, torch.ones(len(params["means"]), dtype=torch.bool, device="cuda"))
            listing = json.loads(sb.download(ASSETS, f"listings/{listing_id}.json"))["market_listing"]["listing"]
            try:
                match = json.loads(sb.download(ASSETS, f"listings/{listing_id}/run/match_gate.json"))
            except RuntimeError:
                match = None
            out = compare_scans.remote(cid, listing_id, listing_ply, res["files"]["splat.ply"], listing, match)
            resp = put_result(out["response"], out["pairs"])
            ev.send("stage", {"scan_id": cid, "stage": "7_listing", "status": resp["status"],
                              "ms": int((time.time() - t0) * 1000)})
            return resp
        except Exception as e:
            if _gpu_dead(e):
                _replace_container(str(e)[:120])
            return put_result(failed("INTERNAL", f"{type(e).__name__}: {e}"), {})
        finally:
            ev.close()

    def _listing_top_spz(self, sb, listing_id: str) -> bytes:
        """The listing splatted from its top lap only (video.mp4), for a rescan that has no underside. Made once per
        listing and cached as assets/splats/{listing_id}.top.spz (not a .json, so no index lists it)."""
        from mintsplat.pipeline import run
        from mintsplat.publish import fetch_inputs
        from supabase_setup.storage import ASSETS

        path = f"splats/{listing_id}.top.spz"
        try:
            return sb.download(ASSETS, path)
        except RuntimeError:
            pass
        _, videos, io = fetch_inputs(sb, listing_id)
        spz = run(self, videos[0], {"ply": False, "debug": False, "views": False,
                                    "rotate_cw": io["rotate_cw"][:1]})["files"]["splat.spz"]
        sb.upload(ASSETS, path, spz, "application/octet-stream")
        return spz

    @modal.method()
    def prewarm(self) -> str:
        """No-op: on_upload calls it as soon as a scan starts (session.json, bottom.mp4), so this container is up with
        its models loaded (@modal.enter) by the time video.mp4 lands; the cold start happens while the seller is still
        recording. (A tiny real warm-up job here saved ~5 s more but once tripped a CUDA assert that poisoned the
        container for the real scan, so it is gone.)"""
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
              .add_local_python_source("supabase_setup", "mintsplat"))
UUID_RE = r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"


@app.function(image=hook_image, secrets=SECRETS, timeout=60)
@modal.asgi_app()
def api():
    """The website's write path (no key in the browser; the service key stays here). CORS is open: the scan id, a
    UUID the seller's browser made, is what names a listing.
      POST /listings/{scan_id}/publish  {state: published | draft, title, description, price_cad}
        -> the listing document (gsplat/mintsplat/market.py set_published)"""
    import re
    from typing import Literal

    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field

    from mintsplat.market import set_published
    from supabase_setup.storage import Supabase

    web = FastAPI(title="Mint listings API")
    web.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST", "OPTIONS"],
                       allow_headers=["Content-Type"])

    class PublishBody(BaseModel):
        state: Literal["published", "draft"]
        title: str = Field(min_length=1, max_length=120)
        description: str = Field(min_length=1, max_length=4000)
        price_cad: int = Field(ge=1, le=100_000)

    @web.post("/listings/{scan_id}/publish")
    def publish_listing(scan_id: str, body: PublishBody) -> dict:
        if not re.fullmatch(UUID_RE, scan_id):
            raise HTTPException(404, "unknown scan")
        if not HAS_SUPABASE:
            raise HTTPException(503, "Modal secret mint-supabase missing")
        try:
            doc = set_published(Supabase(), scan_id, body.state == "published", body.title.strip(),
                                body.description.strip(), body.price_cad)
        except RuntimeError as e:  # Supabase: no such listing document
            raise HTTPException(404, f"no listing for scan {scan_id}") from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"scan_id": scan_id, "published": doc["published"], "price_cad": body.price_cad}

    return web


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
    if file == "rescan.mp4":  # a buyer's verify rescan (uploaded last): compare it with its listing
        if not jobs.put(f"verify:{scan_id}", time.time(), skip_if_exists=True):
            return {"ok": True, "duplicate": scan_id}
        return {"ok": True, "verify": scan_id, "call_id": splatter().run_verify.spawn(scan_id).object_id}
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
