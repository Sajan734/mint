// The website's listing shapes. Same MarketListing as buyer/lib/types.ts (the pipeline Listing nested inside the
// website wrapper). Keep the Grade ... MarketListing block identical to the buyer copy.
export type { ListingDoc, SplatManifest, StageEvent } from "./listing-doc";

// Mirrors listing/contracts.py Listing exactly. Do not add fields here.
export type Grade = "like_new" | "light_wear" | "moderate_wear" | "heavy_wear";
export interface Listing {
  item_id: string;
  title: string;
  description: string;
  attributes: Record<string, string>;
  tags: string[];
  condition_grade: Grade;
  condition_notes: string[];
  price_cad: number; // int > 0
  price_justification: string[];
  preview_images: string[]; // URLs
  viewer_url: string | null; // splat viewer later
  needs_seller_check: boolean;
  seller_check_reasons: string[];
}

export type ListingStatus = "available" | "reserved" | "sold";
export type Category =
  | "home_kitchen"
  | "electronics"
  | "garden_plants"
  | "sports_outdoors"
  | "toys_games"
  | "books_media"
  | "furniture"
  | "clothing_accessories";

// Website wrapper. The pipeline Listing is nested, never flattened.
export interface MarketListing {
  listing: Listing;
  seller_id: string;
  garage_sale_id: string;
  category: Category;
  location: { neighbourhood: string; city: string };
  reference_price_cad: number | null; // Mint fair value for this item in this condition
  frames: string[]; // spin frames, ordered by azimuth, >= 1
  splat_url: string | null; // .spz for a future Spark viewer
  usable_view_count: number; // for "Verified by Mint scan"
  listed_at: string; // ISO-8601
  status: ListingStatus;
}
