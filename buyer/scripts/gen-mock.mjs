// Run once: node scripts/gen-mock.mjs  -> writes mock/*.json, public/avatars/*.svg and ../seller/mock/my-listings.json (outputs are committed).
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const real = join(root, "..", "multiagent");
const out = (p, d) => { mkdirSync(dirname(join(root, p)), { recursive: true }); writeFileSync(join(root, p), typeof d === "string" ? d : JSON.stringify(d, null, 2) + "\n"); };


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
  ["gs_junction_vintage", 2, "Vintage closet clear-out", "A guitar, a chair and pieces collected over ten years.", "2026-10-25", 11, 17, false, "Junction"],
  ["gs_scarborough_gear", 3, "Summer gear and game night", "Sneakers, a toy truck and a few other things.", "2026-10-31", 9, 14, true, "Scarborough Village"],
  ["gs_highland_kids", 4, "Highland Creek kids' stuff", "Outgrown toys and books, gently loved.", "2026-10-24", 9, 13, false, "Highland Creek"],
  ["gs_agincourt_tech", 5, "Agincourt tech upgrade sale", "A camera, a lens and some desk things.", "2026-10-25", 12, 18, true, "Agincourt"],
  ["gs_beaches_ended", 0, "Beaches porch sale", "Our porch sale. It has ended; sold items stay for the record.", "2026-10-10", 10, 15, false, "Leslieville"],
];
const gsales = saleDefs.map(([id, si, name, blurb, day, h0, h1, ships, nb]) => ({
  id, seller_id: sellers[si].id, name, blurb,
  starts_at: `${day}T${String(h0).padStart(2, "0")}:00:00${day > "2026-11-01" ? "-05:00" : "-04:00"}`,
  ends_at: `${day}T${String(h1).padStart(2, "0")}:00:00${day > "2026-11-01" ? "-05:00" : "-04:00"}`,
  pickup_slots: slots(day, h0, 6), ships, location: { neighbourhood: nb, city: "Toronto" },
}));

// ---- items. The two heroes are real photographed listings (pots: real listing-agent output). Every other item is a
// real 3D Gaussian splat published on SuperSplat (superspl.at) under CC BY 4.0 (one CC BY-SA 4.0), streamed from its
// CDN; the pictures are rendered from the same splats (buyer/scripts/render-splats.mjs -> public/demo/splats/{key}/).
// The listing text, prices and sales around them are demo data, written for the demo.
const C = { h: "home_kitchen", e: "electronics", g: "garden_plants", s: "sports_outdoors", t: "toys_games", b: "books_media", f: "furniture", c: "clothing_accessories" };
const CDN = "https://d28zzqy0iyovbz.cloudfront.net";
// Orientation per splat, as a URL fragment the viewer reads (lib/splat-scene.ts fragmentRotation): SuperSplat scenes
// come in their capture tool's axes. Checked by eye on renders.
const ROT = Object.fromEntries(
  ["garden-table", "dragon-lamp", "chair-02", "vanadinite", "chair", "shoe", "toy-truck", "donkey", "trex", "lego-bulldozer",
    "lens", "lego-bonsai", "chair-01", "fruit-bowl", "green-vase"].map((k) => [k, "#rx=180"]),
);
// Turned so the viewer and the first frame face the item's front.
Object.assign(ROT, { elephant: "#rx=-90", "sony-a7": "#rx=180&ry=180", nike: "#ry=-90" });
// key, scene, version, rotation fragment, title, category, sale, price, reference (null: no price check), grade, status,
// colour, description, credit [author, licence]
export const SPLATS = [
  ["garden-table", "87c30a43", "v1", ROT["garden-table"], "Round garden table with vase", C.f, 0, 45, 50, "light_wear", "available", "natural wood", "Round wooden garden table on folding legs. The vase and dried flowers come with it.", ["omaregeh", "CC BY 4.0"]],
  ["dragon-lamp", "210d7b7b", "v2", ROT["dragon-lamp"], "Dragon table lamp", C.h, 1, 40, 35, "like_new", "available", "bronze", "Sculpted dragon lamp for a desk or shelf. Works with a standard E26 bulb.", ["natural_ai", "CC BY 4.0"]],
  ["chair-02", "905d28c7", "v1", ROT["chair-02"], "Mesh office chair, black", C.f, 1, 140, 160, "moderate_wear", "reserved", "black", "Mesh-back office chair with arms and a five-star base. Adjustable height. Some wear on the arms.", ["jazmorow", "CC BY 4.0"]],
  ["vanadinite", "663d6a97", "v1", ROT["vanadinite"], "Vanadinite mineral specimen", C.h, 2, 85, 70, "like_new", "available", "red", "Red vanadinite crystals on matrix, about the size of a fist. A display piece.", ["doudoid", "CC BY 4.0"]],
  ["chair", "6be6e0ce", "v1", ROT["chair"], "Wooden side chair", C.f, 2, 30, 45, "light_wear", "available", "weathered wood", "Solid wooden chair with a slatted back. Weathered finish.", ["quinszouls", "CC BY 4.0"]],
  ["nike", "738cbe49", "v1", ROT["nike"], "Nike sneakers, worn for gardening", C.s, 3, 25, 30, "heavy_wear", "available", "grey", "Comfortable Nike runners, now garden shoes. Clean but well worn.", ["getrakt", "CC BY 4.0"]],
  ["shoe", "0fe63ee8", "v1", ROT["shoe"], "Painted canvas sneaker", C.c, 3, 40, 35, "light_wear", "available", "multicolour", "Hand-painted canvas sneaker. One of a kind.", ["yyw", "CC BY 4.0"]],
  ["toy-truck", "d14f063c", "v1", ROT["toy-truck"], "Toy moving truck", C.t, 3, 20, 25, "light_wear", "reserved", "white", "Toy moving truck with opening back doors.", ["alfred2010", "CC BY 4.0"]],
  ["donkey", "40e18e4c", "v1", ROT["donkey"], "Donkey toy figure", C.t, 4, 10, 12, "like_new", "available", "grey", "Small hand-painted donkey figure.", ["alfred2010", "CC BY 4.0"]],
  ["trex", "d281a49d", "v1", ROT["trex"], "Tyrannosaurus rex toy", C.t, 4, 15, 12, "light_wear", "available", "yellow", "Rubber T. rex figure. Kid-tested.", ["alfred2010", "CC BY 4.0"]],
  ["elephant", "b01bfc43", "v1", ROT["elephant"], "Thai souvenir elephant toy", C.t, 4, 15, 20, "like_new", "reserved", "multicolour", "Fabric elephant from Thailand, bright pattern.", ["shiroeftddee", "CC BY 4.0"]],
  ["lego-bulldozer", "747ff4f8", "v1", ROT["lego-bulldozer"], "LEGO bulldozer, built", C.t, 4, 35, null, "light_wear", "available", "yellow", "Built LEGO bulldozer. All pieces there as far as we can tell.", ["omaregeh", "CC BY 4.0"]],
  ["sony-a7", "467df6a2", "v1", ROT["sony-a7"], "Sony Alpha 7 camera body", C.e, 5, 450, 520, "light_wear", "available", "black", "Sony Alpha 7 full-frame body. Battery and charger included.", ["veryos", "CC BY 4.0"]],
  ["lens", "59cf6487", "v1", ROT["lens"], "7Artisans manual camera lens", C.e, 5, 95, 70, "like_new", "available", "black", "7Artisans manual-focus lens with caps. Clean glass.", ["veryos", "CC BY 4.0"]],
  ["lego-bonsai", "14d76a85", "v1", ROT["lego-bonsai"], "LEGO bonsai tree with pot and stand", C.t, 5, 40, 45, "like_new", "reserved", "green", "Built LEGO bonsai tree on its stand, with the pebbles.", ["omaregeh", "CC BY 4.0"]],
  ["chair-01", "912d1a49", "v1", ROT["chair-01"], "Mesh office chair", C.f, 5, 120, 120, "moderate_wear", "sold", "black", "Mesh office chair with arms. Comfortable for long days; the seat shows wear.", ["jazmorow", "CC BY 4.0"]],
  ["fruit-bowl", "d8ba72a6", "v1", ROT["fruit-bowl"], "Wooden fruit bowl", C.h, 5, 20, 25, "like_new", "sold", "dark wood", "Wide wooden fruit bowl. The fruit is not included.", ["superdelphi", "CC BY 4.0"]],
  ["green-vase", "8d6803b0", "v2", ROT["green-vase"], "Black urn planter with ivy", C.g, 6, 30, 30, "light_wear", "sold", "black", "Black urn planter on a pedestal, planted with ivy.", ["explossive_99", "CC BY-SA 4.0"]],
];

const MULT = { like_new: 0.8, light_wear: 0.65, moderate_wear: 0.5, heavy_wear: 0.35 };
const NOTES = {
  like_new: ["No defects stood out in any view."],
  light_wear: ["2 views show a small scuff."],
  moderate_wear: ["4 views show scratches or scuffs."],
  heavy_wear: ["6 views show scratches or scuffs.", "The sole shows stains."],
};
const src = JSON.parse(readFileSync(join(real, "mock", "listings", "pots_listing.json"), "utf8"));
const heroFrames = (hero) => Array.from({ length: 24 }, (_, n) => `/local/${hero}/f${String(n).padStart(2, "0")}.webp`);
const wrap = (listing, i, { sale, category, ref, frames, splat_url, views, status }) => ({
  listing, seller_id: gsales[sale].seller_id, garage_sale_id: gsales[sale].id, category,
  location: { neighbourhood: gsales[sale].location.neighbourhood, city: "Toronto" },
  reference_price_cad: ref, frames, splat_url, usable_view_count: views,
  listed_at: `2026-10-${String(8 + (i % 8)).padStart(2, "0")}T${String(9 + (i % 9)).padStart(2, "0")}:15:00Z`,
  status,
});
const pots = wrap({ ...src, item_id: "pots_i1", preview_images: [0, 6, 12, 18].map((n) => heroFrames("pots")[n]) }, 0,
  { sale: 0, category: C.g, ref: 30, frames: heroFrames("pots"), splat_url: null, views: 11, status: "available" });
const zen = wrap({
  item_id: "zen_i1", title: "Tabletop zen garden set with rake and stones",
  description: "Tabletop zen garden set with rake and stones. Everyday home piece, easy to clean. Pickup is easy.",
  attributes: { type: "home kitchen", colour: "sand" }, tags: ["tabletop", "zen", "garden", "home"],
  condition_grade: "light_wear", condition_notes: NOTES.light_wear, price_cad: 25,
  price_justification: ["We estimate the used market price at about $35; x 0.65 for light wear gives $23.", "Seller priced it at $25."],
  preview_images: [0, 6, 12, 18].map((n) => heroFrames("zen")[n]), viewer_url: null, needs_seller_check: false, seller_check_reasons: [],
}, 1, { sale: 1, category: C.h, ref: 23, frames: heroFrames("zen"), splat_url: null, views: 10, status: "available" });

const listings = [pots, zen, ...SPLATS.map(([key, scene, ver, rot, title, category, sale, price, ref, grade, status, colour, description, credit], k) => {
  const frames = Array.from({ length: 24 }, (_, n) => `/demo/splats/${key}/f${String(n).padStart(2, "0")}.webp`);
  const checks = key === "chair-01" ? ["The underside was not scanned.", "Condition needs a quick check before publishing."] : [];
  const mkt = ref ? Math.round(ref / MULT[grade]) : null;
  const listing = {
    item_id: `itm_${key.replace(/-/g, "_")}`, title, description,
    attributes: { type: title.toLowerCase(), colour, "3D scan": `${credit[0]} on SuperSplat, ${credit[1]}` },
    tags: [...new Set(title.toLowerCase().replace(/[^a-z0-9 ]/g, "").split(" ").filter((w) => w.length > 3))].slice(0, 4),
    condition_grade: grade, condition_notes: NOTES[grade], price_cad: price,
    price_justification: ref
      ? [`We estimate the used market price at about $${mkt}; x ${MULT[grade]} for ${grade.replace("_", " ")} gives $${ref}.`, `Seller priced it at $${price}.`]
      : ["No comparable sales found yet, so Mint has no price check for this item."],
    preview_images: [0, 6, 12, 18].map((n) => frames[n]), viewer_url: null,
    needs_seller_check: checks.length > 0, seller_check_reasons: checks,
  };
  return wrap(listing, k + 2, { sale, category, ref, frames, splat_url: `${CDN}/${scene}/${ver}/meta.json${rot ?? ""}`, views: 10 + (k % 5), status });
})];

// Credits for the 3D models, shown on the About page (CC BY needs the author and the licence).
out("mock/splat-credits.json", SPLATS.map(([key, scene, , , title, , , , , , , , , [author, licence]]) => (
  { key, title, author, licence, url: `https://superspl.at/scene/${scene}` })));

const fallbacks = { pots_i1: Array.from({ length: 24 }, (_, n) => `/frames/vase/sage/${n}`), zen_i1: Array.from({ length: 24 }, (_, n) => `/frames/boardgame/sand/${n}`) };

const byId = (id) => listings.find((m) => m.listing.item_id === id).listing;
const orders = [
  { id: "ord_seed_meetup", item_id: "itm_elephant", created_at: "2026-10-16T14:05:00Z", method: "meetup", pickup_slot: gsales[4].pickup_slots[2], price_cad: byId("itm_elephant").price_cad, shipping_cad: 0, total_cad: byId("itm_elephant").price_cad, status: "reserved", comparison_id: "fc4b95cb" },
  { id: "ord_seed_shipped", item_id: "itm_toy_truck", created_at: "2026-10-12T18:40:00Z", method: "shipping", ship_to: { name: "Sam Okafor", street: "48 Willowdale Ave", city: "Toronto", postal_code: "M2N 4Y5" }, price_cad: byId("itm_toy_truck").price_cad, shipping_cad: 12, total_cad: byId("itm_toy_truck").price_cad + 12, status: "delivered", comparison_id: "fc4b95cb" },
];

const runPath = join(real, "runs", "fc4b95cb-70e4-4d89-b91e-ea58f4257869", "response.json");
const run = existsSync(runPath) ? JSON.parse(readFileSync(runPath, "utf8")) : null;
const verify = run
  ? {
      _note: "Real buyer-agent output copied from runs/fc4b95cb-70e4-4d89-b91e-ea58f4257869/response.json (subset). Shown in the site as a sample result.",
      comparison_id: "fc4b95cb", status: run.status, verdict_label: run.verdict.label, explanation: run.explanation, error: run.error ?? null,
    }
  : JSON.parse(readFileSync(join(root, "mock", "verify-sample.json"), "utf8")); // the run folder is not on every machine

out("mock/sellers.json", sellers);
out("mock/garage-sales.json", gsales);
out("mock/listings.json", listings);
out("mock/frame-fallbacks.json", fallbacks);
out("mock/orders.json", orders);
out("mock/verify-sample.json", verify);
// ../seller/mock/scan-result.json (what demo mode's scan flow replays) comes from make_demo_assets.py: a real listing.
out("../seller/mock/my-listings.json", listings.filter((m) => m.seller_id === "sel_raj"));
console.log("wrote", listings.length, "listings");
