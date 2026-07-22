const { test, expect } = require("@playwright/test");
const {
  captureSmartShadingBrowserErrors,
} = require("./browser-errors");

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

test("real Home Assistant opens the Smart Shading setup dialog", async ({ page }) => {
  const errors = captureSmartShadingBrowserErrors(page);
  await login(page);
  await page.goto("/config/integrations/dashboard/add?domain=smart_shading");
  await expect(
    page.getByRole("heading", {
      name: "Do you want to set up Smart Shading?",
      exact: true,
    })
  ).toBeVisible();
  await page.getByRole("button", { name: "OK", exact: true }).click();
  await expect(page.getByText("Choose setup type", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "House or area name*", exact: true })
  ).toBeVisible();
  await expect(page.getByText("Setup type *", { exact: true })).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("real HA card binds Easy and Advanced to their config entries", async ({ page }) => {
  const errors = captureSmartShadingBrowserErrors(page);
  await login(page);
  const entities = await page.evaluate(async () => {
    const hass = document.querySelector("home-assistant").hass;
    const rooms = Object.values(hass.states).filter(
      (state) =>
        state.attributes.smart_shading_room_id &&
        Array.isArray(state.attributes.sector_statuses)
    );
    const easy = rooms.find(
      (state) => state.attributes.smart_shading_layout === "compact"
    );
    const advanced = rooms.find(
      (state) => state.attributes.smart_shading_layout === "detailed"
    );
    if (!easy || !advanced) throw new Error("Missing Easy or Advanced room state");
    const resourceUrl = "/smart_shading/shading.js";
    const resources = await hass.callWS({ type: "lovelace/resources/list" });
    if (!resources.some((resource) => resource.url === resourceUrl)) {
      await hass.callWS({
        type: "lovelace/resources/create",
        res_type: "module",
        url: resourceUrl,
      });
    }
    const dashboardPath = "smart-shading-e2e";
    const dashboards = await hass.callWS({ type: "lovelace/dashboards/list" });
    if (!dashboards.some((dashboard) => dashboard.url_path === dashboardPath)) {
      await hass.callWS({
        type: "lovelace/dashboards/create",
        title: "Smart Shading E2E",
        url_path: dashboardPath,
        show_in_sidebar: false,
        require_admin: false,
      });
    }
    await hass.callWS({
      type: "lovelace/config/save",
      url_path: dashboardPath,
      config: {
        title: "Smart Shading E2E",
        views: [{
          title: "Smart Shading E2E",
          path: "binding",
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
    });
    return { easy: easy.entity_id, advanced: advanced.entity_id };
  });
  expect(entities.easy).toContain("sensor.");
  expect(entities.advanced).toContain("sensor.");
  await page.goto("/smart-shading-e2e/binding");
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
