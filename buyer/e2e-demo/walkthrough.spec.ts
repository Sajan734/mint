import { expect, test } from "@playwright/test";

// The demo walk-through end to end, across both zones, in demo mode (HANDOFF.md section 4, step 5):
// landing -> Sell an item -> New listing -> Skip to result -> change the price -> Publish -> the item is in
// "Just listed" -> open it -> Contact seller -> Scan -> Skip to result -> drag the before/after slider.
test("demo walk-through: list an item, find it, contact the seller, check it", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message} @ ${page.url()}`));

  await page.goto("/?mock=1");
  const header = page.getByRole("banner");
  await expect(header.getByText("Demo data")).toBeVisible();

  await header.getByRole("link", { name: "Sell an item" }).click();
  await expect(page).toHaveURL(/\/sell$/);
  await expect(page.getByRole("heading", { name: "Your listings" })).toBeVisible();

  await page.getByRole("link", { name: "New listing" }).click();
  await expect(page).toHaveURL(/\/sell\/scan\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("img", { name: "QR code that opens the Mint app for this scan" })).toBeVisible();
  await page.getByRole("button", { name: "Skip to result" }).click();

  // The editor holds the real listing demo mode replays (seller/mock/scan-result.json).
  await expect(page).toHaveURL(/\/sell\/listing\/[0-9a-f-]{36}$/, { timeout: 15_000 });
  const id = page.url().split("/").pop()!;
  const name = page.getByLabel("Name");
  await expect(name).toHaveValue(/ThinkPad/);
  const title = await name.inputValue();
  await page.getByLabel("Your price").fill("17");
  await page.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Published on this device.")).toBeVisible();

  // Back to the shared landing page (the seller logo is a plain link across zones).
  await page.getByRole("link", { name: "mint", exact: true }).click();
  await expect(page).toHaveURL(/localhost:3000\/$/);
  const justListed = page.getByRole("region", { name: "Just listed" });
  const card = justListed.getByRole("link", { name: title });
  await expect(card).toBeVisible();
  await expect(justListed.getByText("$17")).toBeVisible();
  await card.click();

  await expect(page).toHaveURL(new RegExp(`/listing/${id}$`));
  await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  await page.getByRole("button", { name: "Contact seller" }).click();
  const contact = page.getByRole("dialog");
  await expect(contact.getByRole("link", { name: /@example\.com$/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(contact).toBeHidden();

  await page.getByRole("link", { name: "Scan", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/listing/${id}/check/[^/]+$`));
  await page.getByRole("button", { name: "Skip to result" }).click();

  // A recorded comparison from a different item, and it says so.
  await expect(page.getByText("This recorded check is from a different item")).toBeVisible({ timeout: 15_000 });
  const slider = page.getByRole("slider", { name: "Compare the listing with your scan" });
  const stage = page.getByTestId("wipe-stage").first();
  await stage.scrollIntoViewIfNeeded();
  const box = (await stage.boundingBox())!;
  const before = Number(await slider.inputValue());
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.15, box.y + box.height / 2, { steps: 8 });
  await page.mouse.up();
  const after = Number(await slider.inputValue());
  expect(after).toBeLessThan(before);
  expect(after).toBeLessThanOrEqual(20);
  // The keyboard moves it too (the range input keeps focus after a drag).
  await page.keyboard.press("ArrowRight");
  await expect(slider).toHaveValue(String(after + 1));

  expect(errors).toEqual([]);
});
