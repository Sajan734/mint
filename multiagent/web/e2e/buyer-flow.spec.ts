import { expect, test, type Page } from "@playwright/test";

const errors: string[] = [];
test.beforeEach(({ page }) => {
  page.on("console", (m) => m.type() === "error" && !m.text().startsWith("Failed to load resource") && errors.push(`${m.text()} @ ${page.url()}`));
  page.on("response", (r) => r.status() >= 400 && !r.url().endsWith("/listing/nope") && errors.push(`${r.status()} ${r.url()} from ${r.request().headers()["referer"] ?? page.url()}`));
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message} @ ${page.url()}`));
});
test.afterAll(() => {
  expect(errors).toEqual([]);
});

const cards = (page: Page) => page.locator("article");
const listing = (page: Page) => page.goto("/listing/pots_i1");
const reserve = (page: Page) => page.getByRole("button", { name: /^Reserve for/ }).first();

test("home shows 12 of 40, Show more reveals the rest; filter changes URL and count", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("40 items");
  await expect(cards(page)).toHaveCount(12);
  for (const n of [24, 36, 40]) {
    await page.getByRole("button", { name: /^Show \d+ more$/ }).click();
    await expect(cards(page)).toHaveCount(n);
  }
  await expect(page.getByRole("button", { name: /^Show \d+ more$/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Garden & plants" }).click();
  await expect(page).toHaveURL(/cat=garden_plants/);
  await expect(page.getByRole("status")).toContainText("5 items");
  await expect(cards(page)).toHaveCount(5);
});

test("spin viewer drags and responds to ArrowRight", async ({ page }) => {
  await listing(page);
  const s = page.getByRole("slider").first();
  const val = async () => Number(await s.getAttribute("aria-valuenow"));
  const box = (await s.boundingBox())!;
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down(); // stops the intro turn
  await page.waitForTimeout(200);
  const before = await val();
  await page.mouse.move(cx - 120, cy, { steps: 8 });
  await page.mouse.up();
  await expect.poll(val).not.toBe(before);
  await page.waitForTimeout(1500); // inertia settles
  const mid = await val();
  await s.focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(val).toBe((mid + 1) % (Number(await s.getAttribute("aria-valuemax")) + 1));
});

test("save toggles and shows on /saved", async ({ page }) => {
  await listing(page);
  const save = page.getByRole("button", { name: /^Save / }).first();
  await save.click();
  await expect(page.getByRole("button", { pressed: true, name: "Saved" }).first()).toBeVisible();
  await page.goto("/saved");
  await expect(cards(page)).toHaveCount(1);
});

test("meetup reserve lands on order page and appears in /orders", async ({ page }) => {
  await listing(page);
  await reserve(page).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel(/Meet in person/).check();
  await dlg.getByRole("button", { name: "Continue" }).click();
  await dlg.getByRole("radio").first().check();
  await dlg.getByRole("button", { name: "Continue" }).click();
  await dlg.getByRole("button", { name: /^Reserve for/ }).click();
  await dlg.getByRole("button", { name: "View order" }).click();
  await expect(page).toHaveURL(/\/orders\/[^/]+$/);
  const url = page.url();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.goto("/orders");
  await expect(page.locator(`a[href="${new URL(url).pathname}"]`).first()).toBeVisible();
});

test("shipping order validates address then succeeds; advance reaches verify; rescan explains", async ({ page }) => {
  await listing(page);
  await reserve(page).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel(/Ship to me/).check();
  await dlg.getByRole("button", { name: "Continue" }).click();
  await dlg.getByRole("button", { name: "Continue" }).click();
  await expect(dlg.getByRole("alert")).toContainText("Enter your full name");
  await dlg.getByLabel("Full name").fill("Sam Okafor");
  await dlg.getByLabel("Street address").fill("48 Willowdale Ave");
  await dlg.getByLabel("City").fill("Toronto");
  await dlg.getByLabel("Postal code").fill("bad");
  await dlg.getByRole("button", { name: "Continue" }).click();
  await expect(dlg.getByRole("alert")).toContainText("Canadian postal code");
  await dlg.getByLabel("Postal code").fill("M2N 4Y5");
  await dlg.getByRole("button", { name: "Continue" }).click();
  await dlg.getByRole("button", { name: /and reserve$/ }).click();
  await dlg.getByRole("button", { name: "View order" }).click();
  await expect(page).toHaveURL(/\/orders\/[^/]+$/);

  const adv = page.getByRole("button", { name: /^Advance/ });
  const rescan = page.getByRole("button", { name: "Start rescan" });
  for (let i = 0; i < 6 && !(await rescan.isVisible()); i++) await adv.click();
  await expect(rescan).toBeVisible();
  await rescan.click();
  await expect(page.getByText("Sample result")).toBeVisible({ timeout: 10_000 });
  for (const h of ["What we found", "How sure we are", "Listing vs your item", "What to do", "Things to keep in mind"])
    await expect(page.getByText(h).first()).toBeVisible();
});

test("static pages render; unknown listing 404s", async ({ page }) => {
  await page.goto("/about");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("How Mint works");
  await page.goto("/sale/gs_leslieville_moving");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.goto("/orders/ord_seed_meetup");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  const r = await page.goto("/listing/nope");
  expect(r?.status()).toBe(404);
});
