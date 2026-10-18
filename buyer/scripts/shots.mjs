// Screenshots of every screen at 1280 and 390 px wide, plus the console errors each page logged.
//   node scripts/shots.mjs [out_dir] [base_url]     (defaults: ../docs/web-handoff/shots, http://localhost:3000)
// Needs both apps running (start-web.ps1, or `pnpm start` in seller then buyer). Writes <name>-<width>.png and
// console.json (page -> errors). Live pages read Supabase; ?mock=1 pages replay the recorded demo.
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const out = process.argv[2] ?? "../docs/web-handoff/shots";
const base = (process.argv[3] ?? "http://localhost:3000").replace(/\/$/, "");
const LISTING = "9657403c-0f23-4d16-b5cc-49e305bc5ad6"; // the live demo listing (ThinkPad mouse)
const CHECK = "6f8427df-4b61-4fbd-8ba1-2b36159b33a9"; // a real live buyer check of it, with both splats
const NO_CHECK = "00000000-0000-4000-8000-000000000000"; // a check nobody ran: the waiting state

const SCREENS = [
  ["home", "/?mock=0"],
  ["listing-live", `/listing/${LISTING}?mock=0`],
  ["listing-demo", "/listing/itm_sony_a7?mock=0"],
  ["check-waiting", `/listing/${LISTING}/check/${NO_CHECK}?mock=0`],
  ["check-result", `/listing/${LISTING}/check/${CHECK}?mock=0`],
  ["check-demo", `/listing/itm_sony_a7/check/${NO_CHECK}?mock=1`],
  ["orders", "/orders?mock=0"],
  ["order", "/orders/ord_seed_meetup?mock=0"],
  ["saved", "/saved?mock=0"],
  ["seller", "/seller/sel_priya?mock=0"],
  ["sale", "/sale/gs_leslieville_moving?mock=0"],
  ["about", "/about?mock=0"],
  ["sell", "/sell?mock=0"],
  ["sell-demo", "/sell?mock=1"],
  ["scan-waiting", `/sell/scan/${NO_CHECK}?mock=0`],
  ["scan-demo", `/sell/scan/${NO_CHECK}?mock=1`],
  ["editor-live", `/sell/listing/${LISTING}?mock=0`],
  ["editor-demo", `/sell/listing/${NO_CHECK}?mock=1`], // demo mode replays the recorded listing for any scan id
  ["not-found", "/listing/no-such-item?mock=0"],
];

mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const errors = {};
for (const width of [1280, 390]) {
  const ctx = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 }, deviceScaleFactor: 1 });
  for (const [name, path] of SCREENS) {
    const page = await ctx.newPage();
    const logged = [];
    page.on("console", (m) => m.type() === "error" && logged.push(m.text().slice(0, 300)));
    page.on("pageerror", (e) => logged.push(`pageerror: ${String(e).slice(0, 300)}`));
    await page.goto(base + path, { waitUntil: "load", timeout: 90_000 }).catch((e) => logged.push(`goto: ${e}`));
    await page.waitForTimeout(3500); // live reads, 3D and fonts settle
    const sideways = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (sideways > 0) logged.push(`scrolls sideways by ${sideways}px`);
    // A full-page shot can stall on a live WebGL canvas: fall back to the viewport, and never stop the whole run.
    const file = join(out, `${name}-${width}.png`);
    await page.screenshot({ path: file, fullPage: true, timeout: 20_000 })
      .catch(() => page.screenshot({ path: file, timeout: 20_000 }))
      .catch((e) => logged.push(`screenshot: ${String(e).split("\n")[0]}`));
    if (logged.length) errors[`${name}-${width}`] = logged;
    writeFileSync(join(out, "console.json"), JSON.stringify(errors, null, 1)); // as it goes: a hang later loses nothing
    await page.close();
    console.log(width, name, logged.length ? `${logged.length} issue(s)` : "ok");
  }
  await ctx.close();
}
await browser.close();
