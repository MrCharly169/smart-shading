const { test, expect } = require("@playwright/test");

test("Easy card ignores legacy Advanced override", async ({ page }) => {
  await page.goto("/e2e/ui/harness.html");
  const card = page.locator("#card");
  await expect(card).toContainText("Test Room");
  await expect(card).toContainText("Window");
  await expect(card.locator("[data-advanced]")).toHaveCount(0);
  await expect(card.locator(".target-line")).toHaveCount(0);
  await expect(page.locator("#editor").locator('[data-toggle="advanced_mode"]')).toHaveCount(0);
});

test("Advanced entry enables diagnostics without a card setting", async ({ page }) => {
  await page.goto("/e2e/ui/harness.html");
  await page.evaluate(() => {
    window.fixture.room.attributes.smart_shading_advanced_mode = true;
    window.fixture.card.hass = window.fixture.hass;
  });
  const card = page.locator("#card");
  await expect(card.locator("[data-advanced]")).toHaveCount(1);
  await expect(card.locator(".target-line")).toContainText("25%");
});

test("responsive card remains inside the viewport", async ({ page }) => {
  await page.goto("/e2e/ui/harness.html");
  const box = await page.locator("#card").boundingBox();
  expect(box).not.toBeNull();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize().width);
});
