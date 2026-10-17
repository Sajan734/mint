// Run once: node scripts/gen-mock.mjs  -> writes mock/*.json, public/avatars/*.svg and ../seller/mock/*.json (outputs are committed).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const real = join(root, "..", "multiagent");
const out = (p, d) => { mkdirSync(dirname(join(root, p)), { recursive: true }); writeFileSync(join(root, p), typeof d === "string" ? d : JSON.stringify(d, null, 2) + "\n"); };

// seeded rng + shuffle (mulberry32)
let s = 20261017;
const rnd = () => { s = (s + 0x6d2b79f5) | 0; let t = Math.imul(s ^ (s >>> 15), 1 | s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
const shuffle = (a) => { const b = [...a]; for (let i = b.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [b[i], b[j]] = [b[j], b[i]]; } return b; };
const between = (a, b) => a + rnd() * (b - a);

// ---- sellers
const sellers = [
  ["sel_priya", "Priya N.", "Leslieville", "2026-03", 4.9, 31, "usually replies within an hour"],
  ["sel_marcus", "Marcus T.", "The Annex", "2026-05", 4.8, 22, "usually replies within a few hours"],
  ["sel_amara", "Amara O.", "Junction", "2026-02", 4.7, 18, "usually replies within a day"],
  ["sel_daniel", "Daniel K.", "Scarborough Village", "2026-06", 4.6, 9, "usually replies within an hour"],
  ["sel_hannah", "Hannah L.", "Highland Creek", "2026-04", 5.0, 12, "usually replies within a few hours"],
  ["sel_raj", "Raj S.", "Agincourt", "2026-07", 4.5, 7, "usually replies within a day"],
].map(([id, name, neighbourhood, member_since, rating, rating_count, response_time], i) => ({
  id, name, avatar: `/avatars/${id}.svg`, neighbourhood, member_since, rating, rating_count, response_time,
  // demo-only contact details, reserved fictional values (example.com, 555-01xx)
  email: `${id.slice(4)}@example.com`, phone: `416-555-01${String(i + 1).padStart(2, "0")}`,
}));
sellers.forEach((x, i) => {
  const hue = (i * 57 + 140) % 360;
  const ini = x.name.split(" ").map((w) => w[0]).join("");
  out(`public/avatars/${x.id}.svg`, `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96"><rect width="96" height="96" rx="48" fill="hsl(${hue} 45% 82%)"/><text x="48" y="58" text-anchor="middle" font-family="system-ui,sans-serif" font-size="34" font-weight="600" fill="hsl(${hue} 40% 24%)">${ini}</text></svg>\n`);
});

// ---- garage sales (si = seller index)
const slots = (day, startH, n) => Array.from({ length: n }, (_, i) => { const m = startH * 60 + i * 30; return `${day}T${String(Math.floor(m / 60)).padStart(2, "0")}:${m % 60 ? "30" : "00"}:00-04:00`; });
const saleDefs = [
  ["gs_leslieville_moving", 0, "Moving sale on Queen St", "Packing up a two-bedroom. Everything is scanned and ready to spin.", "2026-10-24", 10, 16, true, "Leslieville"],
  ["gs_danforth_declutter", 1, "Annex declutter weekend", "Lamps, shelves and things that deserve a second home.", "2026-10-24", 10, 15, true, "The Annex"],
  ["gs_junction_vintage", 2, "Vintage closet clear-out", "Coats and pieces collected over ten years.", "2026-10-25", 11, 17, false, "Junction"],
  ["gs_scarborough_gear", 3, "Summer gear and game night", "Helmets, games and camping bits.", "2026-10-31", 9, 14, true, "Scarborough Village"],
  ["gs_highland_kids", 4, "Highland Creek kids' stuff", "Outgrown toys and books, gently loved.", "2026-10-24", 9, 13, false, "Highland Creek"],
  ["gs_agincourt_tech", 5, "Agincourt tech upgrade sale", "Headphones, speakers and desk gear.", "2026-10-25", 12, 18, true, "Agincourt"],
  ["gs_annex_bookshelf", 1, "Annex bookshelf purge", "Shelves cleared, one box at a time.", "2026-11-07", 10, 15, false, "The Annex"],
  ["gs_beaches_ended", 0, "Beaches porch sale", "Our porch sale. It has ended; sold items stay for the record.", "2026-10-10", 10, 15, false, "Leslieville"],
];
const gsales = saleDefs.map(([id, si, name, blurb, day, h0, h1, ships, nb]) => ({
  id, seller_id: sellers[si].id, name, blurb,
  starts_at: `${day}T${String(h0).padStart(2, "0")}:00:00${day > "2026-11-01" ? "-05:00" : "-04:00"}`,
  ends_at: `${day}T${String(h1).padStart(2, "0")}:00:00${day > "2026-11-01" ? "-05:00" : "-04:00"}`,
  pickup_slots: slots(day, h0, 6), ships, location: { neighbourhood: nb, city: "Toronto" },
}));

// ---- items [title, category, shape, palette, price]; first two are heroes
const C = { h: "home_kitchen", e: "electronics", g: "garden_plants", s: "sports_outdoors", t: "toys_games", b: "books_media", f: "furniture", c: "clothing_accessories" };
const items = [
  ["Succulents and houseplants in plastic and terracotta pots on pallet shelf", C.g, "vase", "sage", 30],
  ["Tabletop zen garden set with rake and stones", C.h, "boardgame", "sand", 25],
  ["Stoneware mug set (4)", C.h, "mug", "sage", 25], ["Speckled glaze vase", C.h, "vase", "sand", 35], ["Glass canister trio", C.h, "vase", "mint", 20], ["Enamel camp mug", C.h, "mug", "coral", 15],
  ["Wireless over-ear headphones", C.e, "headphones", "ink", 120], ["Kids on-ear headphones", C.e, "headphones", "coral", 30], ["LED desk lamp", C.e, "lamp", "mint", 25], ["Studio headphones", C.e, "headphones", "sand", 95], ["Bluetooth speaker", C.e, "vase", "ink", 40],
  ["Terracotta planter trio", C.g, "vase", "clay", 20], ["Ceramic hanging planter", C.g, "vase", "sage", 15], ["Glazed plant pot, large", C.g, "vase", "coral", 25], ["Watering can and trowel set", C.g, "mug", "mint", 15],
  ["Cycling helmet", C.s, "helmet", "coral", 35], ["Kids bike helmet", C.s, "helmet", "mint", 20], ["Climbing helmet", C.s, "helmet", "ink", 45], ["Skate helmet", C.s, "helmet", "sand", 25], ["Insulated camping mug", C.s, "mug", "ink", 10],
  ["Wooden puzzle box", C.t, "boardgame", "sand", 20], ["Strategy board game", C.t, "boardgame", "coral", 30], ["Family card game box", C.t, "boardgame", "mint", 15], ["Building blocks set", C.t, "boardgame", "clay", 25], ["Trivia night box", C.t, "boardgame", "ink", 20],
  ["Paperback mystery bundle", C.b, "book", "clay", 15], ["Hardcover cookbook", C.b, "book", "sage", 20], ["Graphic novel set", C.b, "book", "ink", 30], ["Travel guide, Japan", C.b, "book", "coral", 10], ["Art history textbook", C.b, "book", "sand", 40],
  ["Brass floor lamp", C.f, "lamp", "sand", 60], ["Reading lamp, linen shade", C.f, "lamp", "clay", 40], ["Arc floor lamp", C.f, "lamp", "ink", 85], ["Entryway bench", C.f, "boardgame", "ink", 220], ["Oak coffee table", C.f, "boardgame", "clay", 400],
  ["Wool coat", C.c, "jacket", "clay", 90], ["Denim jacket", C.c, "jacket", "ink", 45], ["Rain jacket", C.c, "jacket", "mint", 40], ["Puffer vest", C.c, "jacket", "coral", 55], ["Waxed field jacket", C.c, "jacket", "sage", 110],
];

const kinds = ["great", "fair", "high", "overpriced", "unknown"];
const dist = { great: 12, fair: 16, high: 7, overpriced: 3, unknown: 2 };
// pots (index 0) is fair at ratio 1.0 (real finalize price); shuffle the rest
const pool = shuffle(kinds.flatMap((k) => Array(dist[k] - (k === "fair" ? 1 : 0)).fill(k)));
const badge = ["fair", ...pool];
const grades = ["light_wear", ...shuffle([...Array(10).fill("like_new"), ...Array(15).fill("light_wear"), ...Array(10).fill("moderate_wear"), ...Array(4).fill("heavy_wear")])];
const MULT = { like_new: 0.8, light_wear: 0.65, moderate_wear: 0.5, heavy_wear: 0.35 };
const reserved = new Set([3, 9, 16, 22, 28]);
const sold = new Set([35, 37, 25, 27]); // 25, 27 and 28 are sel_raj's, so the seller dashboard shows how items sold
const check = { 5: ["The back view was unclear."], 12: ["One scuff is hard to read.", "Only 6 usable views."], 20: ["A label could not be read."], 28: ["The base view shows a possible crack."] };
const boundary = { great: [85, 100], fair: [110, 100], high: [130, 100] };
const ratioRange = { great: [0.55, 0.84], fair: [0.9, 1.08], high: [1.13, 1.28], overpriced: [1.4, 1.8] };
const kindOf = (p, r) => { if (r === null) return "unknown"; const x = p / r; return x <= 0.85 ? "great" : x <= 1.1 ? "fair" : x <= 1.3 ? "high" : "overpriced"; };
const usedBoundary = new Set();
const blurbs = {
  home_kitchen: "Everyday kitchen and home piece, easy to clean. Pickup is easy.",
  electronics: "Works as it should. Charger or cable noted in the scan where included.",
  garden_plants: "Good for a sunny sill or a balcony. Drainage holes are included.",
  sports_outdoors: "Ready for the next ride, climb or trip. Straps are adjustable.",
  toys_games: "Complete and ready for game night. Pieces counted before the scan.",
  books_media: "Clean pages and a straight spine. Part of a bundle you can mix and match.",
  furniture: "Solid build, easy to move. Dimensions are on the listing.",
  clothing_accessories: "Sized as marked. Lining and buttons checked on the scan.",
};
const src = JSON.parse(readFileSync(join(real, "mock", "listings", "pots_listing.json"), "utf8"));

const listings = items.map(([title, category, shape, palette, price0], i) => {
  const sale = gsales[Math.floor(i / 5)];
  const seller = sellers.find((x) => x.id === sale.seller_id);
  const grade = grades[i];
  let price = price0, ref;
  const k = badge[i];
  if (i === 0) ref = 30;
  else if (k === "unknown") ref = null;
  else if (boundary[k] && !usedBoundary.has(k) && i > 1) { usedBoundary.add(k); [price, ref] = boundary[k]; }
  else {
    price = Math.max(10, price0);
    const [lo, hi] = ratioRange[k];
    ref = Math.round(price / between(lo, hi));
    for (let n = 0; kindOf(price, ref) !== k && n < 50; n++) ref += kindOf(price, ref) === "great" ? 1 : -1;
    if (kindOf(price, ref) !== k) { price += 5; ref = Math.round(price / ((lo + hi) / 2)); }
  }
  const id = i === 0 ? "pots_i1" : i === 1 ? "zen_i1" : `itm_${String(i + 1).padStart(4, "0")}`;
  const hero = i < 2 ? (i === 0 ? "pots" : "zen") : null;
  const frames = Array.from({ length: 24 }, (_, n) => hero ? `/local/${hero}/f${String(n).padStart(2, "0")}.webp` : `/frames/${shape}/${palette}/${n}`);
  const mkt = ref ? Math.round(ref / MULT[grade]) : null;
  const slug = title.toLowerCase().replace(/[^a-z0-9 ]/g, "");
  const nChk = check[i] ?? [];
  const base = i === 0 ? src : {
    item_id: id, title, description: `${title}. ${blurbs[category]}`,
    attributes: { type: category.replace("_", " "), colour: palette }, tags: [...slug.split(" ").filter((w) => w.length > 2).slice(0, 3), category.split("_")[0]],
    condition_grade: grade,
    condition_notes: grade === "like_new" ? ["No defects found in 11 usable views."] : [`${grade === "heavy_wear" ? 5 : 2} views show ${grade === "light_wear" ? "a small scuff" : "scratches or scuffs"}.`, ...(grade === "heavy_wear" ? ["The base view shows stains or discolouration."] : [])],
    price_cad: price,
    price_justification: ref ? [`We estimate the used market price at about $${mkt}; x ${MULT[grade]} for ${grade.replace("_", " ")} gives $${ref}.`, `Seller priced it at $${price}.`] : ["No comparable sales found yet, so Mint has no price check for this item."],
    preview_images: [], viewer_url: null, needs_seller_check: nChk.length > 0, seller_check_reasons: nChk,
  };
  const listing = { ...base, item_id: id, preview_images: [0, 6, 12, 18].map((n) => frames[n]), ...(i === 0 ? {} : {}) };
  return {
    listing, seller_id: seller.id, garage_sale_id: sale.id, category,
    location: { neighbourhood: sale.location.neighbourhood, city: "Toronto" },
    reference_price_cad: ref, frames, splat_url: null,
    usable_view_count: nChk.length ? 6 : 8 + Math.floor(rnd() * 7),
    listed_at: `2026-10-${String(8 + (i % 8)).padStart(2, "0")}T${String(9 + (i % 9)).padStart(2, "0")}:15:00Z`,
    status: sold.has(i) ? "sold" : reserved.has(i) ? "reserved" : "available",
  };
});

const fallbacks = Object.fromEntries([0, 1].map((i) => [listings[i].listing.item_id, Array.from({ length: 24 }, (_, n) => `/frames/${items[i][2]}/${items[i][3]}/${n}`)]));

const L = (idx) => listings[idx].listing;
const orders = [
  { id: "ord_seed_meetup", item_id: L(3).item_id, created_at: "2026-10-16T14:05:00Z", method: "meetup", pickup_slot: gsales[0].pickup_slots[2], price_cad: L(3).price_cad, shipping_cad: 0, total_cad: L(3).price_cad, status: "reserved", comparison_id: "fc4b95cb" },
  { id: "ord_seed_shipped", item_id: L(9).item_id, created_at: "2026-10-12T18:40:00Z", method: "shipping", ship_to: { name: "Sam Okafor", street: "48 Willowdale Ave", city: "Toronto", postal_code: "M2N 4Y5" }, price_cad: L(9).price_cad, shipping_cad: 12, total_cad: L(9).price_cad + 12, status: "delivered", comparison_id: "fc4b95cb" },
];

const run = JSON.parse(readFileSync(join(real, "runs", "fc4b95cb-70e4-4d89-b91e-ea58f4257869", "response.json"), "utf8"));
const verify = {
  _note: "Real buyer-agent output copied from runs/fc4b95cb-70e4-4d89-b91e-ea58f4257869/response.json (subset). Shown in the site as a sample result.",
  comparison_id: "fc4b95cb", status: run.status, verdict_label: run.verdict.label, explanation: run.explanation, error: run.error ?? null,
};

out("mock/sellers.json", sellers);
out("mock/garage-sales.json", gsales);
out("mock/listings.json", listings);
out("mock/frame-fallbacks.json", fallbacks);
out("mock/orders.json", orders);
out("mock/verify-sample.json", verify);
out("../seller/mock/scan-result.json", listings[0]); // the pots_i1 entry, real listing-agent output
out("../seller/mock/my-listings.json", listings.filter((m) => m.seller_id === "sel_raj"));
console.log("wrote", listings.length, "listings");
