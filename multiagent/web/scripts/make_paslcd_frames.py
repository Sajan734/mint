"""Write 24 evenly spaced PASLCD frames per set to public/local/<set>/fNN.webp (480px centre crop)."""
from pathlib import Path
from PIL import Image

SRC = Path(r"C:\Users\abhin\Downloads\mint\multiagent\data\paslcd")
OUT = Path(__file__).resolve().parent.parent / "public" / "local"
SETS = {"pots": "Pots", "zen": "Zen"}

for name, folder in SETS.items():
    files = sorted((SRC / folder / "Instance_1" / "images").glob("*.*"))
    files = [f for f in files if f.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    if not files:
        raise SystemExit(f"no images for {folder}")
    (OUT / name).mkdir(parents=True, exist_ok=True)
    for i in range(24):
        im = Image.open(files[i * len(files) // 24]).convert("RGB")
        s = min(im.size)
        left, top = (im.width - s) // 2, (im.height - s) // 2
        im.crop((left, top, left + s, top + s)).resize((480, 480), Image.LANCZOS).save(OUT / name / f"f{i:02d}.webp", quality=80)
    print(name, len(files), "->", 24)
