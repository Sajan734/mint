"""The repo-root .env for local Python entry points: the Modal token (MODAL_TOKEN_ID / MODAL_TOKEN_SECRET picks the
workspace every deploy and call goes to) and the keys `modal deploy` sends with the apps. Values already in the
environment win. Empty values are skipped: an empty MODAL_TOKEN_ID would otherwise replace the token with nothing.
"""
import os
from pathlib import Path

ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ROOT_ENV) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if v := v.strip().strip('"').strip("'"):
                os.environ.setdefault(k.strip(), v)


def set_env(key: str, value: str, path: Path = ROOT_ENV) -> bool:
    """Write key=value into the .env, replacing the key's line or appending one. False if it already had it."""
    raw = path.read_bytes().decode("utf-8") if path.is_file() else ""
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines, new = raw.splitlines(), f"{key}={value}"
    hit = [i for i, line in enumerate(lines) if line.split("=", 1)[0].strip() == key]
    if hit and lines[hit[0]] == new:
        return False
    if hit:
        lines[hit[0]] = new
    else:
        lines.append(new)
    path.write_bytes((nl.join(lines) + nl).encode("utf-8"))
    return True
