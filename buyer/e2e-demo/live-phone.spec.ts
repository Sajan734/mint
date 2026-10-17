import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

// Live mode (demo data off) with the PHONE SIMULATED in the browser: the test answers the scan-session function's
// "status" polls the way the Mint app's updates would (waiting -> scanning -> uploading -> uploaded), then serves the
// real published files of a real run (gsplat/out/scan_a6816dfc) for this scan id. Nothing is written to Supabase.
// It checks the page's live wiring: lib/scan-feed.ts watchScan + reduceScan, ScanFlow, and the editor filling from
// the listing document. A real phone run is still needed for the app itself (docs/web-handoff/PROGRESS.md, task E).
const REAL = "../gsplat/out/scan_a6816dfc";
const manifest = JSON.parse(readFileSync(`${REAL}/scan.json`, "utf8")).manifest;
const listingDoc = JSON.parse(readFileSync(`${REAL}/listing.json`, "utf8"));

test("live listing scan: phone status, upload, processing, then the editor fills from the listing", async ({ page }) => {
  let phone: { status: string; passes: number; progress: number } | null = null; // null: the app has not reported
  let published = false;

  await page.route("**/functions/v1/scan-session", async (route) => {
    const body = route.request().postDataJSON() as { action: string; scan_id: string };
    expect(body.action).toBe("status"); // the site only reads; it never requests or updates
    if (!phone) return route.fulfill({ status: 404, json: { error: "no such scan" } });
    return route.fulfill({ json: { v: 1, scan_id: body.scan_id, kind: "listing", ...phone } });
  });
  await page.route("**/storage/v1/object/public/assets/splats/*.json*", (route) =>
    published ? route.fulfill({ json: manifest }) : route.fulfill({ status: 404, json: { error: "not_found" } }),
  );
  await page.route("**/storage/v1/object/public/assets/listings/*.json*", (route) =>
    published ? route.fulfill({ json: listingDoc }) : route.fulfill({ status: 404, json: { error: "not_found" } }),
  );

  await page.goto("/sell?mock=0");
  await expect(page.getByText("Demo data")).toHaveCount(0);
  await page.getByRole("link", { name: "New listing" }).click();
  await expect(page).toHaveURL(/\/sell\/scan\/[0-9a-f-]{36}$/);
  const id = page.url().split("/").pop()!;
  const panel = page.getByRole("region", { name: "Your phone" });
  const step = (label: string) => page.getByRole("region", { name: "Steps" }).getByRole("listitem").filter({ hasText: label });

  // Waiting: the QR encodes this scan's id, exactly as the iOS app expects (scanner/DASHBOARD.md).
  await expect(panel.getByRole("link", { name: "On your iPhone? Open the Mint app" })).toHaveAttribute("href", `mint://scan?id=${id}`);
  await expect(step("Scan this code with your iPhone")).toContainText("Now");

  phone = { status: "scanning", passes: 1, progress: 0 };
  await expect(panel.getByText("Phone connected")).toBeVisible();
  await expect(panel.getByText("1 pass recorded")).toBeVisible();

  phone = { status: "uploading", passes: 2, progress: 0.42 };
  await expect(panel.getByRole("progressbar", { name: "Uploading your scan" })).toHaveAttribute("aria-valuenow", "42");
  await expect(panel.getByText("2 passes · keep the app open")).toBeVisible();

  phone = { status: "uploaded", passes: 2, progress: 1 };
  await expect(panel.getByText("Building your listing")).toBeVisible();

  published = true;
  await expect(panel.getByText("Your listing is ready")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/sell/listing/${id}$`));
  await expect(page.getByLabel("Name")).toHaveValue(listingDoc.market_listing.listing.title);
  await expect(page.getByLabel("Your price")).toHaveValue(String(listingDoc.market_listing.listing.price_cad));
  await expect(page.getByText("Sample 3D, not this item")).toHaveCount(0); // the real splat_url, not a sample
});
