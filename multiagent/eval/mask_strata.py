"""gt-mask area strata and per-stratum "changed" manifests (U30, AM-25).

python -m eval.mask_strata --scene Pots/Instance_1 --out-dir data/paslcd_pairs
Strata: small <2%, medium 2-10%, large >10% of mask area. A stratum with <12 images merges into
its neighbour (logged). One 12-pair case per surviving stratum: seller = reference image,
buyer = test image, nearest camera centre.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from eval.make_paslcd_pairs import (
    N_PAIRS,
    centres,
    default_root,
    greedy_nearest_pairs,
    instance_dir,
    list_images,
    write_manifest,
)

log = logging.getLogger("eval.strata")
SMALL_MAX, MEDIUM_MAX = 0.02, 0.10
ORDER = ["small", "medium", "large"]


def mask_fraction(path: Path) -> float:
    with Image.open(path) as im:
        return float((np.asarray(im.convert("L")) > 0).mean())


def stratum_of(frac: float) -> str:
    return "small" if frac < SMALL_MAX else "medium" if frac <= MEDIUM_MAX else "large"


def merge_small(groups: dict[str, list[str]], min_n: int = N_PAIRS) -> dict[str, list[str]]:
    """Merge any stratum under min_n into an adjacent one (next, else previous); log each merge."""
    parts = [(k, list(groups[k])) for k in ORDER if k in groups]
    while len(parts) > 1:
        i = next((i for i, (_, v) in enumerate(parts) if len(v) < min_n), None)
        if i is None:
            break
        j = i + 1 if i + 1 < len(parts) else i - 1
        lo, hi = sorted((i, j))
        merged = (f"{parts[lo][0]}+{parts[hi][0]}", parts[lo][1] + parts[hi][1])
        log.info(
            "merged stratum %s (%d) into %s (%d)",
            parts[i][0],
            len(parts[i][1]),
            parts[j][0],
            len(parts[j][1]),
        )
        parts[lo : hi + 1] = [merged]
    return dict(parts)


def strata(inst: Path) -> tuple[dict[str, float], dict[str, list[str]]]:
    """(mask fraction per test image name, merged strata of test image names)."""
    fracs = {}
    for name in list_images(inst, "test"):
        mask = inst / "gt_mask" / (Path(name).stem + ".png")
        if not mask.exists():
            raise FileNotFoundError(f"no gt_mask for {name}: {mask}")
        fracs[name] = mask_fraction(mask)
    groups: dict[str, list[str]] = {}
    for name, f in fracs.items():
        groups.setdefault(stratum_of(f), []).append(name)
    return fracs, merge_small(groups)


def build(data_root: Path, scene: str, out_dir: Path) -> dict[str, Path]:
    inst = instance_dir(data_root, scene)
    fracs, groups = strata(inst)
    refs = list_images(inst, "ref")
    cref = centres(inst, refs)
    tag = scene.replace("/", "_").replace("Instance_", "i").lower()
    made: dict[str, Path] = {}
    summary = {"fractions": fracs, "counts": {k: len(v) for k, v in groups.items()}}
    for key, names in groups.items():
        if len(names) < N_PAIRS:
            log.warning("stratum %s has %d images (<%d): no case", key, len(names), N_PAIRS)
            continue
        idx = greedy_nearest_pairs(cref, centres(inst, names))
        pairs = [(inst / "images" / refs[i], inst / "images" / names[j]) for i, j in idx]
        out = out_dir / f"{tag}_changed_{key}" / "pairs.json"
        write_manifest(pairs, out, data_root, f"stratum {key}")
        made[key] = out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{tag}_strata.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--data-root", type=Path, default=default_root())
    args = ap.parse_args(argv)
    if args.data_root is None:
        ap.error("--data-root (or DATA_ROOT in the environment) is required")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    build(args.data_root.resolve(), args.scene, args.out_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
