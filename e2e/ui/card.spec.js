const { test, expect } = require("@playwright/test");

const USERNAME = process.env.HA_E2E_USERNAME || "e2e-owner";
const PASSWORD =
  process.env.HA_E2E_PASSWORD || "e2e-only-disposable-password";

async function login(page) {
  await page.goto("/");
  const username = page.getByRole("textbox", {
    name: "Username",
    exact: true,
  });
  await username.waitFor({ state: "visible" });
  await username.fill(USERNAME);
  await page
    .getByRole("textbox", { name: "Password", exact: true })
    .fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForFunction(() => {
    const root = document.querySelector("home-assistant");
    return Boolean(root && root.hass && root.hass.states);
  });
}

function captureBrowserErrors(page) {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(String(error)));
  return errors;
}

test("real Home Assistant opens the Smart Shading setup dialog", async ({ page }) => {
  const errors = captureBrowserErrors(page);
  await login(page);
  await page.goto("/config/integrations/dashboard/add?domain=smart_shading");
  await expect(page.getByText("Choose setup type", { exact: true })).toBeVisible();
  await expect(page.getByText("House or area name", { exact: true })).toBeVisible();
  await expect(page.getByText("Setup type", { exact: true })).toBeVisible();
  await expect(page.locator("ha-dialog:visible, ha-md-dialog:visible")).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("real HA card binds Easy and Advanced to their config entries", async ({ page }) => {
  const errors = captureBrowserErrors(page);
  await login(page);
  const entities = await page.evaluate(() => {
    const hass = document.querySelector("home-assistant").hass;
    const rooms = Object.values(hass.states).filter(
      (state) =>
        state.attributes.smart_shading_room_id &&
        Array.isArray(state.attributes.sector_statuses)
    );
    const easy = rooms.find(
      (state) => state.attributes.smart_shading_advanced_mode === false
    );
    const advanced = rooms.find(
      (state) => state.attributes.smart_shading_advanced_mode === true
    );
    if (!easy || !advanced) throw new Error("Missing Easy or Advanced room state");
    return hass.callWS({
      type: "lovelace/config/save",
      config: {
        title: "Smart Shading E2E",
        views: [{
          title: "Smart Shading E2E",
          path: "smart-shading-e2e",
          cards: [
            {
              type: "custom:smart-shading-card",
              entity: easy.entity_id,
              // A stale legacy override must not turn an Easy entry Advanced.
              advanced_mode: true,
            },
            {
              type: "custom:smart-shading-card",
              entity: advanced.entity_id,
            },
          ],
        }],
      },
    }).then(() => ({ easy: easy.entity_id, advanced: advanced.entity_id }));
  });
  expect(entities.easy).toContain("sensor.");
  expect(entities.advanced).toContain("sensor.");
  await page.goto("/lovelace/smart-shading-e2e");
  await page.waitForFunction(() => customElements.get("smart-shading-card"));
  const cards = page.locator("smart-shading-card");
  await expect(cards).toHaveCount(2);
  const easyCard = cards.nth(0);
  const advancedCard = cards.nth(1);
  await expect(easyCard).toBeVisible();
  await expect(advancedCard).toBeVisible();
  await expect(easyCard.locator("[data-advanced]")).toHaveCount(0);
  await expect(advancedCard.locator("[data-advanced]")).toHaveCount(1);
  await expect(easyCard.locator('.target-line')).toHaveCount(0);
  await expect(advancedCard.locator('.target-line')).not.toHaveCount(0);
  const easyBox = await easyCard.boundingBox();
  expect(easyBox).not.toBeNull();
  expect(easyBox.x).toBeGreaterThanOrEqual(0);
  expect(easyBox.x + easyBox.width).toBeLessThanOrEqual(
    page.viewportSize().width
  );
  expect(errors).toEqual([]);
});
