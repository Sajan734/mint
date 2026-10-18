"""gsplat/app.py compare_scans, run on this machine: the buyer agent on two existing splats, no rescan and no Modal.

    python multiagent/scripts/compare_local.py <cid> <listing_id> <buyer_scan_id> [--resolve-only] [--profile]
                                               [--publish] [--out DIR]

Reads both splats (assets/splats/{id}.spz, decoded to .ply with spz2ply) and the listing doc from Supabase, then runs
the agent exactly as compare_scans does (upright ICP + CPU point renders, Jev judge, Groq claims, advisor). Keys come
from the repo-root .env. Everything lands in multiagent/scripts/out/ (gitignored): data/{cid}/*.ply, runs/{cid}/ (the
agent's run log and view pairs) and result-{cid}.json.

--resolve-only  align + render only: no Jev or Groq calls (free), prints the timings, writes the view pairs.
--profile       wrap the run in cProfile; writes profile-{cid}.prof and prints the top 30 by cumulative time.
--publish       also writes assets/comparisons/{cid}.json and the buyer splat manifest splats/{cid}.json (with
                #ry, as run_verify does) so the check page shows the result. Off by default: nothing is written
                to Supabase without it. Run `python supabase_setup/backup.py` first.
"""

import argparse
import asyncio
import cProfile
import json
import os
import pstats
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path[:0] = [str(HERE), str(HERE.parent), str(REPO), str(REPO / "gsplat")]

from supabase_setup.backup import load_env

load_env()

import spz2ply

ASSETS = "assets"


def fetch_splats(sb, data_root: Path, cid: str, listing_id: str, buyer_id: str) -> None:
    """Both splats as .ply under data_root/{cid}/; kept between runs (the .spz never changes for a scan id)."""
    folder = data_root / cid
    folder.mkdir(parents=True, exist_ok=True)
    for name, sid in (("listing", listing_id), ("buyer", buyer_id)):
        dest = folder / f"{name}.ply"
        if dest.is_file():
            print(name, sid, "cached", dest)
            continue
        p = spz2ply.decode(sb.download(ASSETS, f"splats/{sid}.spz"))
        dest.write_bytes(spz2ply.to_ply(p))
        print(name, sid, len(p["means"]), "gaussians")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cid")
    ap.add_argument("listing_id")
    ap.add_argument("buyer_id")
    ap.add_argument("--resolve-only", action="store_true")
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--out", type=Path, default=HERE / "out")
    args = ap.parse_args()
    if args.publish and args.resolve_only:
        ap.error("--publish needs a full run (drop --resolve-only)")

    out = args.out.resolve()
    data_root, runs_root = out / "data", out / "runs"
    data_root.mkdir(parents=True, exist_ok=True)
    runs_root.mkdir(parents=True, exist_ok=True)
    os.environ.update(DATA_ROOT=str(data_root), BUYER_AGENT_LIVE="1")

    from supabase_setup.storage import Supabase

    sb = Supabase()
    fetch_splats(sb, data_root, args.cid, args.listing_id, args.buyer_id)

    prof = cProfile.Profile() if args.profile else None
    if prof:
        prof.enable()
    try:
        if args.resolve_only:
            result = resolve_only(args.cid, args.listing_id, runs_root)
        else:
            result = full_run(sb, args.cid, args.listing_id, runs_root)
    finally:
        if prof:
            prof.disable()
            prof.dump_stats(str(out / f"profile-{args.cid}.prof"))
            pstats.Stats(prof).sort_stats("cumulative").print_stats(30)
    (out / f"result-{args.cid}.json").write_text(json.dumps(result, indent=1))
    print("wrote", out / f"result-{args.cid}.json")
    if args.publish:
        publish(sb, args.cid, args.buyer_id, result)


def _request(cid: str, listing_id: str, listing: dict | None, match: dict | None):
    from buyer_agent.listing_adapter import claims_from_listing
    from buyer_agent.models import CompareRequest, ListingMatchCheck, SplatRef

    return CompareRequest(
        comparison_id=cid,
        listing_id=listing_id,
        listing_splat=SplatRef(
            path=f"{cid}/listing.ply", format="ply", up_axis="+y", scan_id=listing_id
        ),
        buyer_splat=SplatRef(path=f"{cid}/buyer.ply", format="ply", up_axis="+y", scan_id=cid),
        claims=claims_from_listing(listing) if listing else None,
        listing_match_check=ListingMatchCheck(
            verdict=match["verdict"], reason=match["reason"][:300]
        )
        if match and match.get("verdict")
        else None,
    )


def _upright_resolver(align_out: dict, timings: dict):
    """compare_scans' upright_resolve (gsplat/app.py), with per-step timings."""
    from buyer_agent import align as align_mod
    from buyer_agent import quality, sources
    from buyer_agent.models import AlignmentMetrics

    def upright_resolve(req, settings, renderer):
        t0 = time.perf_counter()
        a, b = (
            sources._load(settings.data_root, req.listing_splat),
            sources._load(settings.data_root, req.buyer_splat),
        )
        t1 = time.perf_counter()
        issues = quality.precheck(a, b)
        if issues:
            return sources.Resolved([], None, "icp", tuple(issues))
        result = align_mod.align(a, b, upright=True)
        t2 = time.perf_counter()
        fit = {k: v for k, v in result["metrics"].items() if k in AlignmentMetrics.model_fields}
        metrics = AlignmentMetrics(**fit | {"scale": result["scale"]})
        align_out.update(matrix=result["matrix"], ambiguity=result["metrics"].get("ambiguity"))
        pairs = renderer.render(a, b, result["matrix"], result["crop"])
        t3 = time.perf_counter()
        timings.update(
            load_s=round(t1 - t0, 2), align_s=round(t2 - t1, 2), render_s=round(t3 - t2, 2)
        )
        return sources.Resolved(pairs, metrics, "icp")

    return upright_resolve


def resolve_only(cid: str, listing_id: str, runs_root: Path) -> dict:
    from buyer_agent.config import load_settings
    from buyer_agent.render import CpuPointRenderer

    settings = load_settings()
    align_out, timings = {}, {}
    t0 = time.perf_counter()
    resolved = _upright_resolver(align_out, timings)(
        _request(cid, listing_id, None, None),
        settings,
        CpuPointRenderer(settings.render_max_points),
    )
    timings["resolve_s"] = round(time.perf_counter() - t0, 2)
    pairs_dir = runs_root / cid / "resolve"
    pairs_dir.mkdir(parents=True, exist_ok=True)
    for p in resolved.pairs:
        (pairs_dir / f"a_{p.label}.png").write_bytes(p.png_a)
        (pairs_dir / f"b_{p.label}.png").write_bytes(p.png_b)
    result = {
        "timings": timings,
        "views": len(resolved.pairs),
        "quality_issues": list(resolved.quality_issues),
        "alignment": resolved.alignment.model_dump() if resolved.alignment else None,
        "align": align_out,
    }
    print(
        json.dumps(
            {k: result[k] for k in ("timings", "views", "quality_issues", "alignment")}, indent=1
        )
    )
    return result


def full_run(sb, cid: str, listing_id: str, runs_root: Path) -> dict:
    from buyer_agent.api import _default_clients
    from buyer_agent.config import load_settings
    from buyer_agent.pipeline import Deps, compare
    from buyer_agent.render import CpuPointRenderer
    from buyer_agent.runlog import RunLog

    listing = json.loads(sb.download(ASSETS, f"listings/{listing_id}.json", fresh=True))[
        "market_listing"
    ]["listing"]
    try:
        match = json.loads(sb.download(ASSETS, f"listings/{listing_id}/run/match_gate.json"))
    except RuntimeError:
        match = None

    settings = load_settings()
    jev, groq = _default_clients(settings)
    align_out, timings = {}, {}
    deps = Deps(
        settings=settings,
        jev=jev,
        groq=groq,
        renderer=CpuPointRenderer(settings.render_max_points),
        runlog_factory=lambda rid: RunLog(runs_root, rid),
        resolver=_upright_resolver(align_out, timings),
    )
    resp = json.loads(
        asyncio.run(compare(_request(cid, listing_id, listing, match), deps)).model_dump_json()
    )
    print(
        json.dumps(
            {k: resp.get(k) for k in ("status", "verdict", "cause", "timings_ms", "error")},
            indent=1,
        )
    )
    print("resolve steps", timings, "ambiguity", align_out.get("ambiguity"))
    return {"response": resp, "align": align_out, "resolve_timings": timings}


def publish(sb, cid: str, buyer_id: str, result: dict) -> None:
    """The check page's two files, as run_verify writes them. The buyer's splat for the 3D slider is the existing
    scan's manifest under the check's id, turned to the listing's yaw (run_verify's _rotate_to_listing rule) and
    kept out of the listing index (no refresh_index)."""
    from mintsplat.yaw import yaw_deg

    resp, align_out = result["response"], result["align"]
    if resp.get("status") == "failed":
        print("not publishing a failed check")
        return
    man = json.loads(sb.download(ASSETS, f"splats/{buyer_id}.json", fresh=True))
    amb = align_out.get("ambiguity")
    if (
        align_out
        and resp.get("verdict") != "alignment_failed"
        and resp.get("cause") != "misaligned"
        and amb is not None
        and amb <= 0.85
    ):
        url, _, frag = man["splat_url"].partition("#")
        frag = "&".join(
            [p for p in frag.split("&") if p and not p.startswith("ry=")]
            + [f"ry={yaw_deg(align_out['matrix']):.1f}"]
        )
        man["splat_url"] = f"{url}#{frag}"
    man.update(
        scan_id=cid, batch_id=cid, note=f"check made from existing scan {buyer_id} (no rescan)"
    )
    sb.upload(
        ASSETS,
        f"splats/{cid}.json",
        json.dumps(man, indent=1).encode(),
        "application/json",
        cache_control="no-cache",
    )
    sb.upload(
        ASSETS,
        f"comparisons/{cid}.json",
        json.dumps(resp, indent=1).encode(),
        "application/json",
        cache_control="no-cache",
    )
    print("published", f"comparisons/{cid}.json", man["splat_url"])


if __name__ == "__main__":
    main()
