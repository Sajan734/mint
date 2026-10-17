# eval/

PASLCD view-pair builders (views mode, no splats). Data lives in the gitignored `data/` tree.
`DATA_ROOT` = that `data/` dir. Manifest paths are relative to it.

## Fetch (only what is needed, never the zips)

```bash
pip install -U "huggingface_hub[cli]"
mkdir -p data/paslcd && cd data/paslcd
hf download ChamudithaJay/PASLCD --repo-type dataset --local-dir . --include "Pots/*"
hf download ChamudithaJay/PASLCD --repo-type dataset --local-dir . --include "Zen/Instance_1/*"
# tune split (about 0.8 GB more)
hf download ChamudithaJay/PASLCD --repo-type dataset --local-dir . --include "Printing_area/Instance_1/*"
hf download ChamudithaJay/PASLCD --repo-type dataset --local-dir . --include "Porch/Instance_1/*"
```

Each instance: `images/` (`Inst_N_IMG_*.JPG` reference, `Inst_N_test_IMG_*.JPG` test),
`gt_mask/` (`Inst_N_test_IMG_*.png`, test only), `sparse/0/{cameras,images,points3D}.bin`.

## Build manifests (outputs under `data/paslcd_pairs/<case>/`)

```bash
export DATA_ROOT=$PWD/data
# held-out same-scene split (main "same" case)
python -m eval.make_split_pairs --scene Pots/Instance_1 --out data/paslcd_pairs/pots1_same/pairs.json
# changed: reference vs test images of one instance, stratified by gt-mask area
python -m eval.mask_strata --scene Pots/Instance_1 --out-dir data/paslcd_pairs
# generic pairs (same instance = posed, nearest camera centre, else "unposed", index order)
python -m eval.make_paslcd_pairs --a Pots/Instance_1 --b Zen/Instance_1 \
    --out data/paslcd_pairs/pots1_vs_zen1/pairs.json
```

`pairs.json` = `[{label: view_01..view_12, a, b}]`. `sources.json` beside it maps labels to source files.

## CI

`python -m eval.ci_check` fails on any `tests/fixtures/**/*.json` whose `model` differs from the
pin, then runs `pytest -q -m "not live"`.
