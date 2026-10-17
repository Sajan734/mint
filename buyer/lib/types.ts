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

export interface Seller {
  id: string;
  name: string;
  avatar: string; // generated SVG avatar URL
  neighbourhood: string;
  member_since: string;
  rating: number; // 1 decimal, 0-5
  rating_count: number;
  response_time: string; // "usually replies within an hour"
}

export interface GarageSale {
  id: string;
  seller_id: string;
  name: string;
  blurb: string;
  starts_at: string;
  ends_at: string; // ISO
  pickup_slots: string[]; // ISO start times, 30 min each
  ships: boolean;
  location: { neighbourhood: string; city: string };
}

export type FulfilmentMethod = "meetup" | "shipping";
export type OrderStatus =
  | "reserved"
  | "confirmed"
  | "picked_up" // meetup
  | "paid"
  | "shipped"
  | "delivered" // shipping
  | "verified"; // both, after Verify
export interface Order {
  id: string;
  item_id: string;
  created_at: string;
  method: FulfilmentMethod;
  pickup_slot?: string;
  ship_to?: { name: string; street: string; city: string; postal_code: string };
  price_cad: number;
  shipping_cad: number;
  total_cad: number;
  status: OrderStatus;
  comparison_id?: string; // which CompareResult the Verify step shows
}

// Mirrors buyer_agent/models.py Explanation exactly.
export interface Explanation {
  headline: string;
  what_we_compared: string;
  what_we_found: string[];
  how_sure: string;
  listing_vs_item: string[];
  what_to_do: string[];
  caveats: string[];
  disclaimer: string;
  friendly_summary?: string | null;
}
export type VerdictLabel =
  | "same"
  | "different"
  | "uncertain"
  | "alignment_failed"
  | "scan_quality_poor"
  | "listing_rejected";
// The subset of CompareResponse the site uses.
export interface CompareResult {
  comparison_id: string;
  status: "done" | "failed";
  verdict_label: VerdictLabel | null;
  explanation: Explanation | null;
  error: { code: string; message: string } | null;
}
