// node scripts/render-splats.mjs [key...]  -> public/demo/splats/{key}/f00..f23.webp
// The pictures of the demo listings are rendered from the listings' own splats (mock/listings.json, written by
// gen-mock.mjs), with each splat's orientation fragment (#rx=180 ...). Runs Chrome through Playwright on the Mac's GPU
// (Metal); set SOFTWARE=1 to render on the CPU instead (much slower for large splats). Needs network for the splats.
import { createServer } from "node:http";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(root, "scripts", "render-splats.html"));
const only = new Set(process.argv.slice(2));
const items = JSON.parse(readFileSync(join(root, "mock", "listings.json"), "utf8"))
  .filter((m) => m.splat_url?.startsWith("https://"))
  .map((m) => ({ key: m.listing.item_id.slice(4).replace(/_/g, "-"), url: m.splat_url }))
  .filter((m) => !only.size || only.has(m.key));

const server = createServer((_req, res) => { res.writeHead(200, { "Content-Type": "text/html" }); res.end(page); });
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;

for (const { key, url } of items) {
  const browser = await chromium.launch({
    args: process.env.SOFTWARE ? ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] : ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"],
  });
  const tab = await browser.newPage({ viewport: { width: 512, height: 512 } });
  const [src, hash] = url.split("#");
  const rot = new URLSearchParams(hash ?? "");
  const q = new URLSearchParams({ src, rx: rot.get("rx") ?? "0", ry: rot.get("ry") ?? "0", rz: rot.get("rz") ?? "0", size: "512" });
  await tab.goto(`${base}?${q}`);
  await tab.waitForFunction(() => window.status === "ready" || String(window.status).startsWith("error"), null, { timeout: 180000 });
  const status = await tab.evaluate(() => window.status);
  if (status !== "ready") { console.log(key, status); await browser.close(); continue; }
  const frames = await tab.evaluate(() => window.renderFrames(24, 20));
  const out = join(root, "public", "demo", "splats", key);
  mkdirSync(out, { recursive: true });
  frames.forEach((d, i) => writeFileSync(join(out, `f${String(i).padStart(2, "0")}.webp`), Buffer.from(d.split(",")[1], "base64")));
  console.log(key, "ok");
  await browser.close();
}
server.close();
