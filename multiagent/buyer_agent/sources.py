"""Scan sources (U23): path jail, pairs.json manifests, splat load -> precheck -> align -> render."""

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol

from pydantic import ValidationError

from buyer_agent import align as align_mod
from buyer_agent import quality, splat_io
from buyer_agent.config import Settings
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.images import MAX_IMAGE_BYTES
from buyer_agent.models import (
    AlignmentMetrics,
    CompareRequest,
    Label,
    Num,
    SplatRef,
    Strict,
    ViewPair,
    unique_labels,
)

MIN_PAIRS, MAX_PAIRS = 12, 24
MAX_MANIFEST_BYTES = 1024 * 1024
SPLAT_SUFFIXES = frozenset({".ply", ".splat"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg"})
MANIFEST_SUFFIXES = frozenset({".json"})
_RESERVED = frozenset({"CON", "NUL", "PRN", "AUX", *(f"COM{i}" for i in range(1, 10))}) | frozenset(
    f"LPT{i}" for i in range(1, 10)
)
_SPLIT = re.compile(r"[\\/]")


def _invalid(detail: str) -> AgentError:
    return AgentError(ErrorCode.INPUT_INVALID, detail)


def check_rel(rel: str, suffixes: frozenset[str]) -> None:
    """Static path checks (no filesystem). Raises INPUT_INVALID."""
    if not rel or "\x00" in rel or rel[0] in "/\\" or Path(rel).is_absolute():
        raise _invalid("absolute or empty path")
    for part in _SPLIT.split(rel):
        if part in ("", ".", ".."):
            raise _invalid("bad path component")
        if not part.isascii():
            raise _invalid("non-ascii path component")
        if ":" in part:
            raise _invalid("colon in path")
        if part.split(".")[0].rstrip(" ").upper() in _RESERVED:
            raise _invalid("reserved name in path")
    if Path(rel).suffix.lower() not in suffixes:
        raise _invalid("file type not allowed")


def safe_open(root: Path, rel: str, suffixes: frozenset[str]) -> tuple[BinaryIO, int]:
    """Open once under `root`; fstat the open handle and compare with the path (AM-17)."""
    check_rel(rel, suffixes)
    base = root.resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base):
        raise _invalid("path escapes data root")
    try:
        fh = open(target, "rb")  # noqa: SIM115 caller closes
    except FileNotFoundError as exc:
        raise AgentError(ErrorCode.FILE_NOT_FOUND, rel) from exc
    except OSError as exc:
        raise _invalid(f"cannot open: {type(exc).__name__}") from exc
    try:
        if not Path(os.path.realpath(target)).is_relative_to(base):  # re-check after open
            raise _invalid("path escapes data root")
        fd_stat, path_stat = os.fstat(fh.fileno()), os.stat(target)
        same = (fd_stat.st_dev, fd_stat.st_ino) == (path_stat.st_dev, path_stat.st_ino)
        if not same or not stat.S_ISREG(fd_stat.st_mode):
            raise _invalid("file changed or is not a regular file")
        return fh, fd_stat.st_size
    except BaseException:
        fh.close()
        raise


def read_file(root: Path, rel: str, suffixes: frozenset[str], max_bytes: int) -> bytes:
    fh, size = safe_open(root, rel, suffixes)
    with fh:
        if size > max_bytes:
            raise _invalid("file too large")
        return fh.read(max_bytes + 1)[:max_bytes]


class ManifestEntry(Strict):
    label: Label
    a: str
    b: str
    azimuth_deg: Num | None = None
    elevation_deg: Num | None = None


def load_manifest(root: Path, rel: str) -> list[ViewPair]:
    try:
        raw = json.loads(read_file(root, rel, MANIFEST_SUFFIXES, MAX_MANIFEST_BYTES))
        if not isinstance(raw, list):
            raise TypeError("manifest must be a list")
        entries = [ManifestEntry.model_validate(e) for e in raw]
    except (ValueError, TypeError, ValidationError) as exc:
        raise _invalid(f"bad manifest: {type(exc).__name__}") from exc
    if not MIN_PAIRS <= len(entries) <= MAX_PAIRS:
        raise _invalid(f"manifest needs {MIN_PAIRS}-{MAX_PAIRS} pairs, got {len(entries)}")
    unique_labels(e.label for e in entries)
    return [
        ViewPair(
            label=e.label,
            azimuth_deg=e.azimuth_deg,
            elevation_deg=e.elevation_deg,
            png_a=read_file(root, e.a, IMAGE_SUFFIXES, MAX_IMAGE_BYTES),
            png_b=read_file(root, e.b, IMAGE_SUFFIXES, MAX_IMAGE_BYTES),
        )
        for e in entries
    ]


def validate_request_paths(req: CompareRequest) -> None:
    """Cheap static check so traversal gives a 422 before any work (API calls this)."""
    for ref in (req.listing_splat, req.buyer_splat):
        if ref is not None:
            check_rel(ref.path, SPLAT_SUFFIXES)
    if req.view_pairs is not None:
        check_rel(req.view_pairs.manifest_path, MANIFEST_SUFFIXES)


class Renderer(Protocol):
    def render(self, a, b, matrix, crop: dict) -> list[ViewPair]: ...


@dataclass(frozen=True)
class Resolved:
    pairs: list[ViewPair]
    alignment: AlignmentMetrics | None
    alignment_mode: Literal["icp", "skipped_view_pairs"]
    quality_issues: tuple[str, ...] = ()


def _load(root: Path, ref: SplatRef) -> align_mod.Cloud:
    fh, size = safe_open(root, ref.path, SPLAT_SUFFIXES)
    with fh:
        return splat_io.load_cloud(fh, size, ref.format, ref.up_axis)


def resolve(req: CompareRequest, settings: Settings, renderer: Renderer) -> Resolved:
    root = settings.data_root
    if req.view_pairs is not None:
        pairs = load_manifest(root, req.view_pairs.manifest_path)
        return Resolved(pairs, None, "skipped_view_pairs")
    assert req.listing_splat is not None and req.buyer_splat is not None  # model validator
    a, b = _load(root, req.listing_splat), _load(root, req.buyer_splat)
    issues = quality.precheck(a, b)
    if issues:
        return Resolved([], None, "icp", tuple(issues))
    result = align_mod.align(a, b)
    # align() also reports diagnostics (points_used) that the strict response model doesn't carry
    fit = {k: v for k, v in result["metrics"].items() if k in AlignmentMetrics.model_fields}
    metrics = AlignmentMetrics(**fit | {"scale": result["scale"]})
    pairs = renderer.render(a, b, result["matrix"], result["crop"])
    return Resolved(pairs, metrics, "icp")
