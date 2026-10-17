"""Smoke test: send real Jev requests for the match gate and condition questions and print every answer.

    python scripts/jev_smoke.py --baseline path/to/baseline.png --item view1.png [view2.png ...]
                                [--task gate|condition|both] [--repeat N] [--fit]

One request per (task, item image, repeat), all sent concurrently. --fit shrinks images to 1024 px on the long
side, so full-size phone photos aren't rejected. Raw answers are saved to
runs/jev_smoke/<timestamp>.json. Nouls have no confidence field of their own: the value is P(yes), and the
printed confidence is max(P, 1 - P), so 0.5 means the model can't tell.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from PIL import Image as PILImage, ImageOps  # noqa: E402
from typesafe_sdk import AsyncTypeSafeClient, Image, RetryPolicy, SystemOneResponse, TypeSafeError  # noqa: E402

from jev_questions import IMAGE_HEADERS, MODEL, TASKS, WEAR_LEVELS, build_state  # noqa: E402

LIMITS = {
    "min_side_px": 280,
    "max_side_px": 1568,
    "max_image_bytes": 16 * 1024 * 1024,
    "max_request_bytes": 32 * 1024 * 1024,
}
FIT = {"long_side_px": 1024, "jpeg_quality": 95}  # --fit
REQUEST = {"timeout_s": 30.0, "max_retries": 1, "concurrency": 8}
EXIF_ORIENTATION = 274


class ImageProblem(Exception):
    pass


def encode(img: PILImage.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **({"quality": FIT["jpeg_quality"]} if fmt == "JPEG" else {}))
    return buf.getvalue()


def load_image(path: Path, fit: bool = False) -> tuple[bytes, str]:
    """Returns the bytes to send and a short description.

    Rotates pixels upright if EXIF says so. With `fit`, shrinks the long side to FIT["long_side_px"]
    (never enlarges).
    """
    data = path.read_bytes()
    with PILImage.open(io.BytesIO(data)) as img:
        fmt = img.format
        if fmt not in ("PNG", "JPEG"):
            raise ImageProblem(f"{path}: {fmt} is not PNG or JPEG")
        out, notes = img, []
        if img.getexif().get(EXIF_ORIENTATION, 1) != 1:
            out = ImageOps.exif_transpose(img)
            notes.append("rotated upright from EXIF")
        if fit and max(out.size) > FIT["long_side_px"]:
            w0, h0 = out.size
            out = out.copy()
            out.thumbnail((FIT["long_side_px"], FIT["long_side_px"]), PILImage.Resampling.LANCZOS)
            notes.append(f"shrunk from {w0}x{h0}")
        if notes:
            data = encode(out, fmt)
        w, h = out.size
    if not (LIMITS["min_side_px"] <= min(w, h) and max(w, h) <= LIMITS["max_side_px"]):
        hint = "; try --fit" if not fit and max(w, h) > LIMITS["max_side_px"] else ""
        raise ImageProblem(
            f"{path}: {w}x{h} px; each side must be {LIMITS['min_side_px']}-{LIMITS['max_side_px']} px "
            f"(Jev rejects, it doesn't resize){hint}"
        )
    if len(data) > LIMITS["max_image_bytes"]:
        raise ImageProblem(f"{path}: {len(data) / 2**20:.1f} MiB is over 16 MiB")
    note = "".join(f", {n}" for n in notes)
    return data, f"{fmt} {w}x{h}, {len(data) / 1024:.0f} KiB{note}"


def answers_to_dict(resp: SystemOneResponse) -> dict:
    out = {}
    for qid, a in resp.answers.items():
        if a.type == "noul":
            out[qid] = {"type": "noul", "p_yes": a.noul}
        elif a.type == "score":
            out[qid] = {
                "type": "score",
                "score": a.score,
                "confidence": a.confidence,
                "probabilities": {WEAR_LEVELS[k] if qid == "wear" else str(k): v for k, v in sorted(a.probabilities.items())},
            }
        else:
            out[qid] = a.model_dump()
    return out


def format_result(task: str, item: Path, info: str, repeat: int, result: dict) -> str:
    lines = [f"=== {task} | {item.name} ({info}) | run {repeat + 1} ==="]
    if "error" in result:
        lines.append(f"  ERROR: {result['error']}")
        return "\n".join(lines)
    lines.append(
        f"  model {result['model']} | {result['latency_ms']:.0f} ms | "
        f"tokens in {result['usage']['input_tokens']} / out {result['usage']['output_tokens']}"
    )
    for qid, a in result["answers"].items():
        if a["type"] == "noul":
            p = a["p_yes"]
            lines.append(f"  {qid:<24} P(yes) {p:.3f}   confidence {max(p, 1 - p):.3f}")
        elif a["type"] == "score":
            top = len(a["probabilities"]) - 1
            probs = ", ".join(f"{k} {v:.2f}" for k, v in a["probabilities"].items())
            lines.append(f"  {qid:<24} score {a['score']:.2f}/{top}   confidence {a['confidence']:.3f}   [{probs}]")
        else:
            lines.append(f"  {qid:<24} {a}")
    return "\n".join(lines)


async def ask(client, sem, task, baseline, item_img) -> dict:
    context, questions = TASKS[task]
    async with sem:
        start = time.perf_counter()
        try:
            resp = await client.system_one(
                state=build_state(context, baseline, item_img),
                questions=questions,
                extra_headers=IMAGE_HEADERS,
            )
        except TypeSafeError as e:
            return {"error": f"{type(e).__name__}: {e}"}
        latency_ms = (time.perf_counter() - start) * 1000
    return {
        "model": resp.model,
        "latency_ms": latency_ms,
        "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
        "answers": answers_to_dict(resp),
    }


async def run(args) -> int:
    tasks = ["gate", "condition"] if args.task == "both" else [args.task]
    try:
        baseline_bytes, baseline_info = load_image(args.baseline, args.fit)
        items = [(p, *load_image(p, args.fit)) for p in args.item]
    except (ImageProblem, OSError) as e:
        print(f"Image problem: {e}", file=sys.stderr)
        return 2
    for p, data, _ in items:
        if len(baseline_bytes) + len(data) > LIMITS["max_request_bytes"]:
            print(f"Image problem: baseline + {p} is over 32 MiB per request", file=sys.stderr)
            return 2

    print(f"baseline: {args.baseline} ({baseline_info})")
    baseline = Image(baseline_bytes)
    item_imgs = {p: Image(data) for p, data, _ in items}
    jobs = [(task, p, info, r) for task in tasks for p, _, info in items for r in range(args.repeat)]

    sem = asyncio.Semaphore(REQUEST["concurrency"])
    async with AsyncTypeSafeClient(
        model=MODEL, timeout=REQUEST["timeout_s"], retry=RetryPolicy(max_retries=REQUEST["max_retries"])
    ) as client:
        results = await asyncio.gather(*(ask(client, sem, task, baseline, item_imgs[p]) for task, p, _, _ in jobs))

    for (task, p, info, r), result in zip(jobs, results):
        print()
        print(format_result(task, p, info, r, result))

    out_dir = ROOT / "runs" / "jev_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    record = {
        "baseline": str(args.baseline),
        "requests": [
            {"task": task, "item": str(p), "repeat": r, **result} for (task, p, _, r), result in zip(jobs, results)
        ],
    }
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\nsaved {out.relative_to(ROOT)}")
    failed = sum("error" in r for r in results)
    if failed:
        print(f"{failed} of {len(results)} requests failed", file=sys.stderr)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Send real Jev requests and print every answer.")
    parser.add_argument("--baseline", type=Path, required=True, help="clean product photo (PNG or JPEG)")
    parser.add_argument("--item", type=Path, nargs="+", required=True, help="one or more item renders or photos")
    parser.add_argument("--task", choices=["gate", "condition", "both"], default="both")
    parser.add_argument("--repeat", type=int, default=1, help="send each request N times to see run-to-run noise")
    parser.add_argument(
        "--fit",
        action="store_true",
        help=f"shrink images to {FIT['long_side_px']} px on the long side (for phone photos)",
    )
    args = parser.parse_args()

    load_dotenv(ROOT.parent / ".env")  # the repo-wide .env
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        print("TYPESAFE_API_KEY is missing: add it to the repo-root .env", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
