// Twin: seller/lib/listing-doc.ts (keep identical)
// What the pipeline publishes under assets/ in Supabase Storage, as far as the sites read it. The document wrapper
// is gsplat/mintsplat/market.py's assets/listings/{scan_id}.json; market_listing is the FULL website MarketListing.
import type { MarketListing } from "./types";

export interface ListingDoc {
  v: number;
  scan_id: string;
  status: "listed" | "rejected" | "failed";
  market_listing?: MarketListing;
  rejection?: { match_check: { verdict: string; reason: string } };
  error?: string;
  spin_urls?: string[];
  timings_ms?: Record<string, number>;
}

/** assets/splats/{scan_id}.json, published when the 3D scan is ready. */
export interface SplatManifest {
  scan_id: string;
  splat_url: string;
  spin_urls?: string[];
  stage_timings_ms: Record<string, number>;
}

/** Realtime `stage` event payload (supabase_setup/storage.py Events, inside the v3 envelope). */
export interface StageEvent {
  scan_id: string;
  stage: string;
  status: string;
  ms: number;
}
