// What the pipeline publishes, as far as the seller site reads it. Listing mirrors listing/contracts.py; the
// document wrapper is gsplat/mintsplat/market.py's assets/listings/{scan_id}.json.
export type Grade = "like_new" | "light_wear" | "moderate_wear" | "heavy_wear";

export interface Listing {
  item_id: string;
  title: string;
  description: string;
  attributes: Record<string, string>;
  tags: string[];
  condition_grade: Grade;
  condition_notes: string[];
  price_cad: number;
  price_justification: string[];
  preview_images: string[];
  viewer_url: string | null;
  needs_seller_check: boolean;
  seller_check_reasons: string[];
}

export interface MarketListing {
  listing: Listing;
  category: string;
  reference_price_cad: number | null;
  frames: string[];
  splat_url: string | null;
  usable_view_count: number;
  listed_at: string;
}

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
