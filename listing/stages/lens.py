"""Google Lens (through Serper) on a couple of the item's photos: visual matches with product titles, for identify.

Lens needs a public image URL. A photo's View.source_url is used when the input gave one; otherwise the resized photo
is uploaded to the public Supabase bucket (assets/listing-photos/<item>/<view>.jpg) with the service-role key.
The photos are searched concurrently. Everything here can fail (no key, no network, a slow search): callers get an
empty list and a log saying why, and identify goes on with what was read off the item.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

import timing
from contracts import View, Views, backed_by_text

LISTING_ROOT = Path(__file__).resolve().parent.parent

LENS = {
    "endpoint": "https://google.serper.dev/lens",
    "photo_picks": (0, 0.5),  # which photos: the first, and the one halfway through (another side of the item)
    "max_matches_per_photo": 30,  # the best-ranked matches are the relevant ones
    "timeout_s": 15.0,
    "user_agent": "MintListing/0.1",  # generic; never personal details
    "bucket": "assets",
    "upload_prefix": "listing-photos",
    "upload_timeout_s": 15.0,
}


@dataclass(frozen=True)
class LensMatch:
    title: str
    source: str | None
    link: str | None
    view_id: str


# --- decisions (pure) -------------------------------------------------------------------------


def picked_views(views: Views) -> list[View]:
    n = len(views.views)
    indexes = dict.fromkeys(min(n - 1, int(p * n)) if isinstance(p, float) else min(n - 1, p)
                            for p in LENS["photo_picks"])
    return [views.views[i] for i in indexes]


def parse_matches(payload: dict[str, Any], view_id: str) -> list[LensMatch]:
    matches = []
    for item in (payload.get("organic") or [])[: LENS["max_matches_per_photo"]]:
        title = " ".join(str(item.get("title") or "").split())
        if title:
            matches.append(LensMatch(title=title, source=item.get("source") or None, link=item.get("link") or None,
                                     view_id=view_id))
    return matches


def support(value: str | None, matches: list[LensMatch]) -> tuple[int, int]:
    """How widely Lens backs `value`: (titles that contain it, distinct sources among them). Ignores case, spaces and
    punctuation, like backed_by_text."""
    if not value:
        return 0, 0
    hits = [m for m in matches if backed_by_text(value, [m.title])]
    sources = {(m.source or m.link or m.title).casefold() for m in hits}
    return len(hits), len(sources)


def titles_for_prompt(matches: list[LensMatch], limit: int) -> list[str]:
    """Distinct titles, best-ranked first, alternating between the photos so both sides are represented."""
    by_view: dict[str, list[str]] = {}
    for m in matches:
        by_view.setdefault(m.view_id, []).append(m.title)
    out, seen = [], set()
    for rank in range(max((len(v) for v in by_view.values()), default=0)):
        for titles in by_view.values():
            if rank < len(titles) and titles[rank].casefold() not in seen:
                seen.add(titles[rank].casefold())
                out.append(titles[rank])
    return out[:limit]


# --- I/O --------------------------------------------------------------------------------------


def _env(name: str) -> str:
    load_dotenv(LISTING_ROOT.parent / ".env")  # the repo-wide .env
    return os.environ.get(name, "").strip()


async def upload_photo(client: httpx.AsyncClient, view: View, item_id: str) -> str:
    """Puts the resized photo in the public bucket; returns its public URL."""
    base, key = _env("SUPABASE_URL").rstrip("/"), _env("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        raise RuntimeError("no public URL for the photo and no SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY to upload it")
    path = f"{LENS['bucket']}/{LENS['upload_prefix']}/{item_id}/{view.view_id}.jpg"
    data = (LISTING_ROOT / view.image_path).read_bytes()
    resp = await client.post(f"{base}/storage/v1/object/{path}", content=data, timeout=LENS["upload_timeout_s"],
                             headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "image/jpeg",
                                      "x-upsert": "true"})
    resp.raise_for_status()
    return f"{base}/storage/v1/object/public/{path}"


async def search_one(client: httpx.AsyncClient, view: View, item_id: str, serper_key: str) -> tuple[list[LensMatch], dict]:
    log: dict[str, Any] = {"view_id": view.view_id}
    try:
        url = view.source_url
        if not url:
            with timing.span("upload"):
                url = await upload_photo(client, view, item_id)
            log["uploaded"] = True
        log["url"] = url
        with timing.span("serper"):
            resp = await client.post(LENS["endpoint"], json={"url": url}, timeout=LENS["timeout_s"],
                                     headers={"X-API-KEY": serper_key, "Content-Type": "application/json",
                                              "User-Agent": LENS["user_agent"]})
        resp.raise_for_status()
        matches = parse_matches(resp.json(), view.view_id)
    except (httpx.HTTPError, OSError, RuntimeError, ValueError) as e:
        log["error"] = f"{type(e).__name__}: {e}"
        return [], log
    log["matches"] = len(matches)
    return matches, log


async def lens_matches(views: Views, item_id: str) -> tuple[list[LensMatch], dict[str, Any]]:
    """Lens matches for the picked photos, searched concurrently. Never raises."""
    serper_key = _env("SERPER_API_KEY")
    if not serper_key:
        return [], {"error": "SERPER_API_KEY is missing"}
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*(search_one(client, v, item_id, serper_key) for v in picked_views(views)))
    matches = [m for found, _ in results for m in found]
    return matches, {"photos": [log for _, log in results], "matches": [asdict(m) for m in matches]}
