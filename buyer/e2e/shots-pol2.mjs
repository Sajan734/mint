// Usage: node e2e/shots-pol2.mjs (needs `next start -p 3112` running)
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const base = "http://localhost:3112";
const out = "e2e/shots/pol2";
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();

for (const [w, h] of [[1280, 900], [390, 844]]) {
  for (const scheme of ["light", "dark"]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: scheme, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const tag = `${w}-${scheme}`;
    await page.goto(`${base}/listing/pots_i1`);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${out}/listing-${tag}.png`, fullPage: w === 1280 });
    await page.screenshot({ path: `${out}/listing-bottom-${tag}.png`, clip: undefined });
    // reserve sheet, shipping path to step 2 with an error
    await page.getByRole("button", { name: /^Reserve for/ }).last().click();
    const dlg = page.getByRole("dialog");
    await dlg.getByLabel(/Ship to me/).check();
    await dlg.getByRole("button", { name: "Continue" }).click();
    await dlg.getByRole("button", { name: "Continue" }).click();
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${out}/reserve-${tag}.png` });
    await dlg.getByLabel("Full name").fill("Sam Okafor");
    await dlg.getByLabel("Street address").fill("48 Willowdale Ave");
    await dlg.getByLabel("City").fill("Toronto");
    await dlg.getByLabel("Postal code").fill("M2N 4Y5");
    await dlg.getByRole("button", { name: "Continue" }).click();
    await dlg.getByRole("button", { name: /and reserve$/ }).click();
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${out}/reserved-${tag}.png` });
    await dlg.getByRole("button", { name: "View order" }).click();
    await page.waitForURL(/\/orders\//);
    const adv = page.getByRole("button", { name: /^Advance/ });
    const rescan = page.getByRole("button", { name: "Start rescan" });
    for (let i = 0; i < 6 && !(await rescan.isVisible()); i++) await adv.click();
    await rescan.click();
    await page.getByText("Sample result").waitFor({ timeout: 10000 });
    await page.screenshot({ path: `${out}/order-${tag}.png`, fullPage: true });
    await page.goto(`${base}/about`);
    await page.screenshot({ path: `${out}/about-${tag}.png`, fullPage: true });
    await ctx.close();
  }
}
await browser.close();
