"""Niantic `.spz` -> Cloud via the `gsply` package (MIT; optional dependency, `pip install gsply`).

Not wired into SplatRef/pipeline: `.spz` is not an accepted `format` yet (see LISTING_ADAPT.md).
"""

from pathlib import Path

import numpy as np

from buyer_agent.align import Cloud
from buyer_agent.errors import AgentError, ErrorCode
from buyer_agent.splat_io import SH_C0, SplatLimits, _finite, _orient

MAX_FILE_BYTES = SplatLimits().max_file_bytes


def _bad(detail: str) -> AgentError:
    return AgentError(ErrorCode.SPLAT_UNREADABLE, detail)


def load_spz_cloud(path: Path | str, up_axis: str = "-y", max_points: int = 3_000_000) -> Cloud:
    """Decode a .spz (gzip v1-3 or NGSP v4) into a +Y-up Cloud. Same conventions as `.ply`."""
    try:
        import gsply
    except ImportError as exc:
        raise _bad("spz support needs `pip install gsply`") from exc
    p = Path(path)
    size = p.stat().st_size if p.is_file() else 0
    if not 0 < size <= MAX_FILE_BYTES:
        raise _bad("file size out of range")
    try:
        data = gsply.read_spz(p)
    except Exception as exc:
        raise _bad(f"spz parse error: {type(exc).__name__}") from exc
    if not 0 < len(data.means) <= max_points:
        raise _bad("vertex count out of range")
    points = np.asarray(data.means, np.float64)
    logs = np.asarray(data.scales, np.float64)
    dc = np.asarray(data.sh0, np.float64)
    raw = np.clip(np.asarray(data.opacities, np.float64), -60, 60)
    _finite(points, logs, dc, raw)
    cloud = Cloud(
        points,
        1.0 / (1.0 + np.exp(-raw)),
        np.exp(np.clip(logs, -30, 10)).max(axis=1),
        np.clip(0.5 + SH_C0 * dc, 0.0, 1.0),
    )
    return _orient(cloud, up_axis)  # type: ignore[arg-type]
