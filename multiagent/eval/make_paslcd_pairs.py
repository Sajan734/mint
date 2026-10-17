"""Build a views-mode pairs.json from PASLCD images (U26).

python -m eval.make_paslcd_pairs --a Pots/Instance_1 --b Pots/Instance_1 --a-set ref --b-set test \
    --out data/paslcd_pairs/pots1_changed/pairs.json [--data-root data]

Same instance on both sides -> COLMAP camera centres pair them (nearest, greedy unique).
Different instances/scenes have unrelated frames -> index order, labelled "unposed".
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

from buyer_agent.images import normalise_png
from eval.colmap_bin import read_images_bin

log = logging.getLogger("eval.pairs")
N_PAIRS = 12
_FILTERS = {"ref": lambda n: "_test_" not in n, "test": lambda n: "_test_" in n}


def instance_dir(data_root: Path, rel: str) -> Path:
    return data_root / "paslcd" / rel


def list_images(inst: Path, kind: str) -> list[str]:
    names = sorted(p.name for p in (inst / "images").iterdir() if p.suffix.lower() == ".jpg")
    return [n for n in names if _FILTERS[kind](n)]


def centres(inst: Path, names: list[str]) -> np.ndarray:
    reg = read_images_bin(inst / "sparse" / "0" / "images.bin")
    missing = [n for n in names if n not in reg]
    if missing:
        raise ValueError(f"{len(missing)} images not registered in images.bin, e.g. {missing[0]}")
    return np.stack([reg[n].center for n in names])


def registered_counts(inst: Path) -> tuple[int, int]:
    """(# Inst_N_IMG_*, # Inst_N_test_IMG_*) registered in images.bin (AM-27)."""
    reg = read_images_bin(inst / "sparse" / "0" / "images.bin")
    test = sum("_test_" in n for n in reg)
    return len(reg) - test, test


def greedy_nearest_pairs(ca: np.ndarray, cb: np.ndarray, n: int = N_PAIRS) -> list[tuple[int, int]]:
    """Closest (a, b) index pairs first; each index used once. Sorted by a index."""
    d = np.linalg.norm(ca[:, None, :] - cb[None, :, :], axis=2)
    order = np.dstack(np.unravel_index(np.argsort(d, axis=None, kind="stable"), d.shape))[0]
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for i, j in order:
        if int(i) in used_a or int(j) in used_b:
            continue
        used_a.add(int(i))
        used_b.add(int(j))
        pairs.append((int(i), int(j)))
        if len(pairs) == n:
            break
    return sorted(pairs)


def write_manifest(
    pairs: list[tuple[Path, Path]], out: Path, data_root: Path, note: str = ""
) -> list[dict[str, str]]:
    """Normalise each image to 1024 px PNG beside `out`; write [{label, a, b}] (relative paths)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []
    sources: list[dict[str, str]] = []
    for k, (pa, pb) in enumerate(pairs, 1):
        label = f"view_{k:02d}"
        rel = {}
        for side, src in (("a", pa), ("b", pb)):
            dst = out.parent / f"{label}_{side}.png"
            dst.write_bytes(normalise_png(src.read_bytes()))
            rel[side] = dst.relative_to(data_root).as_posix()
        entries.append({"label": label, **rel})
        sources.append({"label": label, "a": pa.name, "b": pb.name})
    out.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    out.with_name("sources.json").write_text(json.dumps(sources, indent=1), encoding="utf-8")
    log.info("wrote %d pairs to %s %s", len(entries), out, note)
    return entries


def build(
    data_root: Path, a: str, b: str, a_set: str, b_set: str, out: Path
) -> list[dict[str, str]]:
    ia, ib = instance_dir(data_root, a), instance_dir(data_root, b)
    na, nb = list_images(ia, a_set), list_images(ib, b_set)
    if ia == ib:
        idx = greedy_nearest_pairs(centres(ia, na), centres(ib, nb))
        note = "posed"
    else:  # unposed: evenly spaced indices, no geometry claim
        k = min(N_PAIRS, len(na), len(nb))
        idx = [
            (int(i), int(j))
            for i, j in zip(
                np.linspace(0, len(na) - 1, k).round(), np.linspace(0, len(nb) - 1, k).round()
            )
        ]
        note = "unposed"
    if len(idx) < N_PAIRS:
        raise ValueError(f"only {len(idx)} pairs available, need {N_PAIRS}")
    return write_manifest(
        [(ia / "images" / na[i], ib / "images" / nb[j]) for i, j in idx], out, data_root, note
    )


def default_root() -> Path | None:
    v = os.environ.get("DATA_ROOT")
    return Path(v) if v else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--a", required=True, help="seller instance, e.g. Pots/Instance_1")
    ap.add_argument("--b", required=True, help="buyer instance")
    ap.add_argument("--a-set", choices=["ref", "test"], default="ref")
    ap.add_argument("--b-set", choices=["ref", "test"], default="ref")
    ap.add_argument("--out", required=True, type=Path, help="pairs.json path under data root")
    ap.add_argument("--data-root", type=Path, default=default_root())
    args = ap.parse_args(argv)
    if args.data_root is None:
        ap.error("--data-root (or DATA_ROOT in the environment) is required")
    root = args.data_root.resolve()
    inst = instance_dir(root, args.a)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    if (inst / "sparse" / "0" / "images.bin").exists():
        log.info("images.bin %s registers (ref, test) = %s", args.a, registered_counts(inst))
    build(root, args.a, args.b, args.a_set, args.b_set, args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
