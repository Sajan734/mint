"""Held-out same-scene split (U30, AM-25).

python -m eval.make_split_pairs --scene Pots/Instance_1 --out data/paslcd_pairs/pots1_same/pairs.json
Sorted `Inst_N_IMG_*` refs: even index -> seller side, odd -> buyer side. 12 pairs, nearest camera
centre, never the same image.
"""

import argparse
import logging
import sys
from pathlib import Path

from eval.make_paslcd_pairs import (
    N_PAIRS,
    centres,
    default_root,
    greedy_nearest_pairs,
    instance_dir,
    list_images,
    registered_counts,
    write_manifest,
)

log = logging.getLogger("eval.split")


def split_sides(names: list[str]) -> tuple[list[str], list[str]]:
    names = sorted(names)
    return names[0::2], names[1::2]


def build(data_root: Path, scene: str, out: Path) -> list[dict[str, str]]:
    inst = instance_dir(data_root, scene)
    seller, buyer = split_sides(list_images(inst, "ref"))
    idx = greedy_nearest_pairs(centres(inst, seller), centres(inst, buyer), N_PAIRS)
    if len(idx) < N_PAIRS:
        raise ValueError(f"only {len(idx)} pairs available, need {N_PAIRS}")
    pairs = [(inst / "images" / seller[i], inst / "images" / buyer[j]) for i, j in idx]
    if any(a == b for a, b in pairs):
        raise ValueError("pair uses the same image on both sides")
    return write_manifest(pairs, out, data_root, "split")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scene", required=True, help="e.g. Pots/Instance_1")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--data-root", type=Path, default=default_root())
    args = ap.parse_args(argv)
    if args.data_root is None:
        ap.error("--data-root (or DATA_ROOT in the environment) is required")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    root = args.data_root.resolve()
    counts = registered_counts(instance_dir(root, args.scene))
    log.info("images.bin registers (ref, test) = %s", counts)
    build(root, args.scene, args.out.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
