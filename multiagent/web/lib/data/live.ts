// Live listings from the scan pipeline: phone video -> splat (gsplat run_scan) -> listing/ (Jev) -> Supabase
// assets/listings/index.json (public, no key). Each document there with status "listed" carries a MarketListing.
import { MarketListingSchema } from "../schema";
import type { MarketListing } from "../types";

const DEFAULT_SUPABASE_URL = "https://jpanyhsifoxxiizkgjno.supabase.co"; // public project URL, not a secret
const TIMEOUT_MS = 3000;

export const liveIndexUrl = () =>
  `${(process.env.MINT_SUPABASE_URL || DEFAULT_SUPABASE_URL).replace(/\/$/, "")}/storage/v1/object/public/assets/listings/index.json`;

/** Listed scans that pass the site's schema, in index order (newest first). Anything else is skipped. */
export function parseLiveIndex(json: unknown): MarketListing[] {
  const scans = (json as { scans?: unknown } | null)?.scans;
  if (!Array.isArray(scans)) return [];
  return scans.flatMap((doc: { status?: unknown; market_listing?: unknown }) => {
    if (doc?.status !== "listed") return [];
    const parsed = MarketListingSchema.safeParse(doc.market_listing);
    return parsed.success ? [parsed.data] : [];
  });
}

/** Never throws: no index, a slow network or bad data all mean "no live listings", and the mock site still works.
 *  Off in unit tests (they use mock data only) unless MINT_LIVE_LISTINGS=1; MINT_LIVE_LISTINGS=0 turns it off. */
export async function getLiveListings(): Promise<MarketListing[]> {
  const flag = process.env.MINT_LIVE_LISTINGS;
  if (flag === "0" || (process.env.VITEST && flag !== "1")) return [];
  try {
    const res = await fetch(liveIndexUrl(), { cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS) });
    return res.ok ? parseLiveIndex(await res.json()) : [];
  } catch {
    return [];
  }
}
