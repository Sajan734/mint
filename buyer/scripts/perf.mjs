// Web vitals for the key pages on a running site, with Playwright and the browser's Performance API.
//   node scripts/perf.mjs [base_url] [runs]     (defaults: http://localhost:3000, 3)
// Measure production builds (`pnpm build && pnpm start` in seller, then buyer), not dev servers. Two profiles:
// desktop (1280 px, no throttling) and phone (390 px, CPU slowed 4x, like Lighthouse's mobile run). Prints the
// median of `runs` cold loads per page: LCP, CLS, TBT (long tasks after first paint, 10 s window), FCP, and the
// JavaScript the page downloaded (KB, compressed, as sent).
import { chromium } from "@playwright/test";

const base = (process.argv[2] ?? "http://localhost:3000").replace(/\/$/, "");
const runs = Number(process.argv[3] ?? 3);
const LISTING = "9657403c-0f23-4d16-b5cc-49e305bc5ad6";
const CHECK = "6f8427df-4b61-4fbd-8ba1-2b36159b33a9";
const PAGES = [
  ["home", "/?mock=0"],
  ["listing", `/listing/${LISTING}?mock=0`],
  ["check", `/listing/${LISTING}/check/${CHECK}?mock=0`],
  ["sell", "/sell?mock=0"],
];
const PROFILES = [
  { name: "desktop", viewport: { width: 1280, height: 900 }, cpu: 1 },
  { name: "phone", viewport: { width: 390, height: 844 }, cpu: 4 },
];

// Runs in the page before any of its scripts.
const OBSERVE = () => {
  const v = { lcp: 0, cls: 0, longtasks: [] };
  window.__vitals = v;
  new PerformanceObserver((l) => l.getEntries().forEach((e) => (v.lcp = e.startTime))).observe({ type: "largest-contentful-paint", buffered: true });
  new PerformanceObserver((l) => l.getEntries().forEach((e) => { if (!e.hadRecentInput) v.cls += e.value; })).observe({ type: "layout-shift", buffered: true });
  new PerformanceObserver((l) => l.getEntries().forEach((e) => v.longtasks.push([e.startTime, e.duration]))).observe({ type: "longtask", buffered: true });
};

const median = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];

const browser = await chromium.launch();
const rows = [];
for (const prof of PROFILES) {
  for (const [name, path] of PAGES) {
    const samples = [];
    for (let i = 0; i < runs; i++) {
      const ctx = await browser.newContext({ viewport: prof.viewport, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      await page.addInitScript(OBSERVE);
      const cdp = await ctx.newCDPSession(page);
      await cdp.send("Network.enable");
      await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
      if (prof.cpu > 1) await cdp.send("Emulation.setCPUThrottlingRate", { rate: prof.cpu });
      await page.goto(base + path, { waitUntil: "load", timeout: 120_000 });
      await page.waitForTimeout(10_000);
      const s = await page.evaluate(() => {
        const v = window.__vitals;
        const fcp = performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? 0;
        const tbt = v.longtasks.filter(([t]) => t >= fcp && t <= fcp + 10_000).reduce((a, [, d]) => a + Math.max(0, d - 50), 0);
        const js = performance.getEntriesByType("resource").filter((r) => r.initiatorType === "script" || /\.js(\?|$)/.test(r.name))
          .reduce((a, r) => a + (r.transferSize || r.encodedBodySize || 0), 0);
        const nav = performance.getEntriesByType("navigation")[0];
        return { lcp: v.lcp, cls: v.cls, tbt, fcp, js: js + 0, ttfb: nav?.responseStart ?? 0 };
      });
      samples.push(s);
      await ctx.close();
    }
    const m = (k) => median(samples.map((s) => s[k]));
    const row = { profile: prof.name, page: name, lcp_ms: Math.round(m("lcp")), cls: +m("cls").toFixed(3), tbt_ms: Math.round(m("tbt")),
      fcp_ms: Math.round(m("fcp")), ttfb_ms: Math.round(m("ttfb")), js_kb: Math.round(m("js") / 1024) };
    rows.push(row);
    console.log(JSON.stringify(row));
  }
}
await browser.close();
console.table(rows);
