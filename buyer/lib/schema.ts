import { z } from "zod";

const grade = z.enum(["like_new", "light_wear", "moderate_wear", "heavy_wear"]);
const place = z.object({ neighbourhood: z.string(), city: z.string() });

export const ListingSchema = z.object({
  item_id: z.string(),
  title: z.string(),
  description: z.string(),
  attributes: z.record(z.string(), z.string()),
  tags: z.array(z.string()),
  condition_grade: grade,
  condition_notes: z.array(z.string()),
  price_cad: z.number().int().positive(),
  price_justification: z.array(z.string()),
  preview_images: z.array(z.string()),
  viewer_url: z.string().nullable(),
  needs_seller_check: z.boolean(),
  seller_check_reasons: z.array(z.string()),
});

export const MarketListingSchema = z.object({
  listing: ListingSchema,
  seller_id: z.string(),
  garage_sale_id: z.string(),
  category: z.enum(["home_kitchen", "electronics", "garden_plants", "sports_outdoors", "toys_games", "books_media", "furniture", "clothing_accessories"]),
  location: place,
  reference_price_cad: z.number().positive().nullable(),
  frames: z.array(z.string()).min(1),
  splat_url: z.string().nullable(),
  usable_view_count: z.number().int().nonnegative(),
  listed_at: z.string(),
  status: z.enum(["available", "reserved", "sold"]),
});

export const SellerSchema = z.object({
  id: z.string(), name: z.string(), avatar: z.string(), neighbourhood: z.string(), member_since: z.string(),
  rating: z.number().min(0).max(5), rating_count: z.number().int(), response_time: z.string(),
});

export const GarageSaleSchema = z.object({
  id: z.string(), seller_id: z.string(), name: z.string(), blurb: z.string(), starts_at: z.string(), ends_at: z.string(),
  pickup_slots: z.array(z.string()), ships: z.boolean(), location: place,
});

export const OrderSchema = z.object({
  id: z.string(), item_id: z.string(), created_at: z.string(),
  method: z.enum(["meetup", "shipping"]),
  pickup_slot: z.string().optional(),
  ship_to: z.object({ name: z.string(), street: z.string(), city: z.string(), postal_code: z.string() }).optional(),
  price_cad: z.number(), shipping_cad: z.number(), total_cad: z.number(),
  status: z.enum(["reserved", "confirmed", "picked_up", "paid", "shipped", "delivered", "verified"]),
  comparison_id: z.string().optional(),
});

export const CompareResultSchema = z.object({
  comparison_id: z.string(),
  status: z.enum(["done", "failed"]),
  verdict_label: z.enum(["same", "different", "uncertain", "alignment_failed", "scan_quality_poor", "listing_rejected"]).nullable(),
  explanation: z
    .object({
      headline: z.string(), what_we_compared: z.string(), what_we_found: z.array(z.string()), how_sure: z.string(),
      listing_vs_item: z.array(z.string()), what_to_do: z.array(z.string()), caveats: z.array(z.string()),
      disclaimer: z.string(), friendly_summary: z.string().nullish(),
    })
    .nullable(),
  error: z.object({ code: z.string(), message: z.string() }).nullable(),
});
