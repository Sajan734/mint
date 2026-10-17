"""Phone video -> clean object-only Gaussian splat on a Modal GPU.

    modal run app.py --video orbit.mp4                      # full run -> out/<video stem>/
    modal run app.py --video orbit.mp4 --stop-after masks   # iterate on one stage

Outputs land in out/<name>/: splat.ply plus debug JPEGs and timings.json.
"""
import json
import time
from pathlib import Path

import modal

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
    .add_local_python_source("mintsplat")
)

app = modal.App("mint-gsplat", image=image)
models_vol = modal.Volume.from_name("mint-models", create_if_missing=True)


@app.cls(gpu="L40S", volumes={"/models": models_vol}, timeout=900, scaledown_window=300)
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
    def run(self, video: bytes, cfg: dict) -> dict:
        from mintsplat.pipeline import run

        return run(self, video, cfg)


@app.local_entrypoint()
def main(video: str, name: str = "", n_frames: int = 80, stop_after: str = "", iters: int = 4000,
         cap: int = 300_000):
    src = Path(video)
    out_dir = Path("out") / (name or src.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"n_frames": n_frames, "stop_after": stop_after or None,
           "train": {"iters": iters, "cap_max": cap}}

    t0 = time.perf_counter()
    res = Splatter().run.remote(src.read_bytes(), cfg)
    wall = time.perf_counter() - t0

    for fname, data in res.pop("files").items():
        (out_dir / fname).write_bytes(data)
    res["wall_incl_upload_and_cold_start"] = round(wall, 1)
    (out_dir / "run.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    print(f"\nwrote {out_dir}/")
