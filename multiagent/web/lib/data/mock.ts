// Loads and validates mock/*.json once (throws on bad data).
import { z } from "zod";
import { CompareResultSchema, GarageSaleSchema, MarketListingSchema, OrderSchema, SellerSchema } from "../schema";
import listingsJson from "../../mock/listings.json";
import sellersJson from "../../mock/sellers.json";
import salesJson from "../../mock/garage-sales.json";
import ordersJson from "../../mock/orders.json";
import verifyJson from "../../mock/verify-sample.json";
import fallbackJson from "../../mock/frame-fallbacks.json";

export const listings = z.array(MarketListingSchema).parse(listingsJson);
export const sellers = z.array(SellerSchema).parse(sellersJson);
export const garageSales = z.array(GarageSaleSchema).parse(salesJson);
export const orders = z.array(OrderSchema).parse(ordersJson);
export const verifySample = CompareResultSchema.parse(verifyJson);
/** item_id -> 24 procedural frame URLs, for hero listings whose real frames live in gitignored public/local. */
export const frameFallbacks = z.record(z.string(), z.array(z.string())).parse(fallbackJson);
