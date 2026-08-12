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
            {
              type: "custom:smart-shading-card",
              entity: advanced.entity_id,
              // Hiding operational actions must not hide the read-only
              // Advanced trace, simulation, and day-preview entry point.
              show_actions: false,
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
  await expect(cards).toHaveCount(3);
  const easyCard = cards.nth(0);
  const advancedCard = cards.nth(1);
  const detailsOnlyCard = cards.nth(2);
  await expect(easyCard).toBeVisible();
  await expect(advancedCard).toBeVisible();
  await expect(detailsOnlyCard).toBeVisible();
  await expect(easyCard.locator("[data-advanced]")).toHaveCount(0);
  await expect(advancedCard.locator("[data-advanced]")).toHaveCount(1);
  await expect(detailsOnlyCard.locator("[data-advanced]")).toHaveCount(1);
  await expect(detailsOnlyCard.locator("[data-press]")).toHaveCount(0);
  await expect(easyCard.locator('.target-line')).toHaveCount(0);
  await expect(advancedCard.locator('.target-line')).not.toHaveCount(0);
  const easyBox = await easyCard.boundingBox();
  expect(easyBox).not.toBeNull();
  expect(easyBox.x).toBeGreaterThanOrEqual(0);
  expect(easyBox.x + easyBox.width).toBeLessThanOrEqual(
    page.viewportSize().width
  );
  const advancedBox = await advancedCard.boundingBox();
  expect(advancedBox).not.toBeNull();
  expect(advancedBox.x).toBeGreaterThanOrEqual(0);
  expect(advancedBox.x + advancedBox.width).toBeLessThanOrEqual(
    page.viewportSize().width
  );

  await advancedCard.locator("[data-advanced]").click();
  const dialog = page.locator("smart-shading-dialog");
  await expect(dialog).toHaveCount(1);
  await expect(dialog.locator("[data-decision-trace]")).toBeVisible();
  const testTools = dialog.locator("[data-test-tools]");
  const testToolsToggle = testTools.locator('[data-collapse-toggle="tools"]');
  await expect(testToolsToggle).toBeVisible();
  await expect(testToolsToggle).toHaveAttribute("aria-expanded", "false");
  await testToolsToggle.click();
  await expect(testToolsToggle).toHaveAttribute("aria-expanded", "true");
  const previewDate = dialog.locator("input[data-preview-date]");
  const previewAction = dialog.locator("button[data-preview-day]");
  await expect(previewDate).toBeVisible();
  await expect(previewAction).toBeVisible();
  const selectedDate = "2031-06-21";
  await previewDate.fill(selectedDate);
  await previewAction.click();
  await expect.poll(async () => page.evaluate(({ entityId }) => {
    const state = document.querySelector("home-assistant").hass.states[entityId];
    const preview = state?.attributes?.day_preview || {};
    return preview.preview?.day || preview.day || "";
  }, { entityId: entities.advanced })).toBe(selectedDate);
  await expect(dialog.locator("main")).not.toContainText("highest_matching_priority");
  await expect(dialog.locator("main")).not.toContainText("rule_not_matched");
  const dialogBox = await dialog.locator(".dialog").boundingBox();
  expect(dialogBox).not.toBeNull();
  expect(dialogBox.x).toBeGreaterThanOrEqual(0);
  expect(dialogBox.x + dialogBox.width).toBeLessThanOrEqual(
    page.viewportSize().width
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await dialog.locator("[data-close]").last().click();
  await expect(dialog).toHaveCount(0);

  await detailsOnlyCard.locator("[data-advanced]").click();
  await expect(dialog.locator("[data-decision-trace]")).toBeVisible();
  await dialog.locator("[data-close]").last().click();
  await expect(dialog).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("live Card updates never write dashboard scroll or replace stable nodes", async ({ page }) => {
  const errors = captureSmartShadingBrowserErrors(page);
  await login(page);
  const advancedEntity = await page.evaluate(async () => {
    const hass = document.querySelector("home-assistant").hass;
    const advanced = Object.values(hass.states).find(
      (state) => state.attributes.smart_shading_layout === "detailed"
        && state.attributes.smart_shading_room_id
    );
    if (!advanced) throw new Error("Missing Advanced room state");
    const resourceUrl = "/smart_shading/shading.js";
    const resources = await hass.callWS({ type: "lovelace/resources/list" });
    if (!resources.some((resource) => resource.url === resourceUrl)) {
      await hass.callWS({
        type: "lovelace/resources/create",
        res_type: "module",
        url: resourceUrl,
      });
    }
    const dashboardPath = "smart-shading-scroll-e2e";
    const dashboards = await hass.callWS({ type: "lovelace/dashboards/list" });
    if (!dashboards.some((dashboard) => dashboard.url_path === dashboardPath)) {
      await hass.callWS({
        type: "lovelace/dashboards/create",
        title: "Smart Shading Scroll E2E",
        url_path: dashboardPath,
        show_in_sidebar: false,
        require_admin: false,
      });
    }
    await hass.callWS({
      type: "lovelace/config/save",
      url_path: dashboardPath,
      config: {
        title: "Smart Shading Scroll E2E",
        views: [{
          title: "Scroll regression",
          path: "regression",
          cards: [{
            type: "custom:smart-shading-card",
            entity: advanced.entity_id,
          }],
        }],
      },
    });
    return advanced.entity_id;
  });
  await page.goto("/smart-shading-scroll-e2e/regression");
  await page.waitForFunction(() => customElements.get("smart-shading-card"));

  const result = await page.evaluate(async (expectedEntity) => {
    const ha = document.querySelector("home-assistant");
    const hass = ha.hass;
    const roomState = Object.values(hass.states).find(
      (state) => state.entity_id === expectedEntity
    );
    if (!roomState) throw new Error("Missing Advanced room state");
    const coverId = roomState.attributes.configuration.sectors
      .flatMap((sector) => sector.layers)
      .flatMap((layer) => layer.covers)[0]?.entity;
    if (!coverId || !hass.states[coverId]) throw new Error("Missing Advanced cover state");

    const container = document.createElement("div");
    container.style.cssText = "position:fixed;left:8px;top:8px;width:520px;height:280px;overflow:auto;z-index:999999;background:#111";
    const before = document.createElement("div");
    before.style.height = "360px";
    const card = document.createElement("smart-shading-card");
    const after = document.createElement("div");
    after.style.height = "500px";
    container.append(before, card, after);
    document.body.appendChild(container);
    card.setConfig({ entity: roomState.entity_id });
    card.hass = hass;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    container.scrollTop = 300;
    const focusProbe = document.createElement("button");
    focusProbe.textContent = "Outside focus probe";
    focusProbe.style.cssText = "position:fixed;right:0;bottom:0";
    document.body.appendChild(focusProbe);
    focusProbe.focus({ preventScroll: true });

    const documentScroller = document.scrollingElement;
    const originalDocumentScroll = documentScroller.scrollTop;
    const originalWindowScroll = window.scrollY;
    const scrollDescriptor = Object.getOwnPropertyDescriptor(Element.prototype, "scrollTop");
    let documentScrollWrites = 0;
    if (scrollDescriptor?.get && scrollDescriptor?.set) {
      Object.defineProperty(documentScroller, "scrollTop", {
        configurable: true,
        get() { return scrollDescriptor.get.call(this); },
        set(value) {
          documentScrollWrites += 1;
          scrollDescriptor.set.call(this, value);
        },
      });
    }

    const stableCard = card.shadowRoot.querySelector("ha-card");
    const stableMode = card.shadowRoot.querySelector(".mode");
    const stableCover = card.shadowRoot.querySelector(".cover-row");
    const initialRenderCount = Number(card.dataset.renderCount || 0);
    const initialMarkup = card.shadowRoot.innerHTML;

    const stateWith = (state, attributes) => ({
      ...state,
      attributes: { ...state.attributes, ...attributes },
    });
    const hassWith = (updates) => {
      const next = Object.create(hass);
      next.states = { ...hass.states, ...updates };
      return next;
    };

    card.hass = hassWith({
      [roomState.entity_id]: stateWith(roomState, {
        diagnostic_events: [{ event: "room_evaluated", mode: roomState.state }],
      }),
    });
    await new Promise((resolve) => requestAnimationFrame(resolve));
    const diagnosticOnlyRenderCount = Number(card.dataset.renderCount || 0);

    for (let index = 0; index < 8; index += 1) {
      const cover = hass.states[coverId];
      card.hass = hassWith({
        [coverId]: stateWith(cover, { current_position: 91 - index }),
        [roomState.entity_id]: stateWith(roomState, {
          reason: `Visible update ${index}`,
        }),
      });
    }
    await Promise.resolve();
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await new Promise((resolve) => setTimeout(resolve, 1100));

    const cardChecks = {
      containerScroll: container.scrollTop,
      documentScroll: documentScroller.scrollTop,
      windowScroll: window.scrollY,
      documentScrollWrites,
      focusStable: document.activeElement === focusProbe,
      cardStable: card.shadowRoot.querySelector("ha-card") === stableCard,
      modeStable: card.shadowRoot.querySelector(".mode") === stableMode,
      coverStable: card.shadowRoot.querySelector(".cover-row") === stableCover,
      diagnosticOnlySkipped: diagnosticOnlyRenderCount === initialRenderCount,
      visibleChanged: card.shadowRoot.innerHTML !== initialMarkup,
    };

    card.shadowRoot.querySelector("[data-advanced]").click();
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const dialog = document.querySelector("smart-shading-dialog");
    const dialogScroller = dialog.shadowRoot.querySelector(".dialog");
    const stableMain = dialog.shadowRoot.querySelector("main");
    const stableOverview = stableMain.querySelector("section");
    dialogScroller.scrollTop = Math.min(180, dialogScroller.scrollHeight - dialogScroller.clientHeight);
    const dialogScroll = dialogScroller.scrollTop;
    const focusedDialogControl = dialog.shadowRoot.querySelector("[data-close]:last-of-type")
      || dialog.shadowRoot.querySelector("[data-close]");
    focusedDialogControl?.focus({ preventScroll: true });
    const dialogFocus = dialog.shadowRoot.activeElement;

    card.hass = hassWith({
      [roomState.entity_id]: stateWith(roomState, {
        diagnostic_events: [
          { event: "room_evaluated", mode: roomState.state },
          { event: "diagnostic_level", level: "full" },
        ],
      }),
    });
    await Promise.resolve();
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    await new Promise((resolve) => setTimeout(resolve, 1100));

    const dialogChecks = {
      scrollStable: dialogScroller.scrollTop === dialogScroll,
      mainStable: dialog.shadowRoot.querySelector("main") === stableMain,
      overviewStable: dialog.shadowRoot.querySelector("main section") === stableOverview,
      focusStable: dialog.shadowRoot.activeElement === dialogFocus,
      documentScrollWrites,
    };

    dialog.close();
    container.remove();
    focusProbe.remove();
    if (Object.hasOwn(documentScroller, "scrollTop")) delete documentScroller.scrollTop;

    return {
      cardChecks,
      dialogChecks,
      roomAttributeBytes: new TextEncoder().encode(
        JSON.stringify(roomState.attributes)
      ).length,
      hasCardYaml: Object.hasOwn(roomState.attributes, "card_yaml"),
      hasBadgeYaml: Object.hasOwn(roomState.attributes, "badge_yaml"),
      expectedContainerScroll: 300,
      expectedDocumentScroll: originalDocumentScroll,
      expectedWindowScroll: originalWindowScroll,
    };
  }, advancedEntity);

  expect(result.cardChecks.containerScroll).toBe(result.expectedContainerScroll);
  expect(result.cardChecks.documentScroll).toBe(result.expectedDocumentScroll);
  expect(result.cardChecks.windowScroll).toBe(result.expectedWindowScroll);
  expect(result.cardChecks.documentScrollWrites).toBe(0);
  expect(result.cardChecks.focusStable).toBeTruthy();
  expect(result.cardChecks.cardStable).toBeTruthy();
  expect(result.cardChecks.modeStable).toBeTruthy();
  expect(result.cardChecks.coverStable).toBeTruthy();
  expect(result.cardChecks.diagnosticOnlySkipped).toBeTruthy();
  expect(result.cardChecks.visibleChanged).toBeTruthy();
  expect(result.dialogChecks.scrollStable).toBeTruthy();
  expect(result.dialogChecks.mainStable).toBeTruthy();
  expect(result.dialogChecks.overviewStable).toBeTruthy();
  expect(result.dialogChecks.focusStable).toBeTruthy();
  expect(result.dialogChecks.documentScrollWrites).toBe(0);
  expect(result.roomAttributeBytes).toBeLessThan(16_384);
  expect(result.hasCardYaml).toBeFalsy();
  expect(result.hasBadgeYaml).toBeFalsy();
  expect(errors).toEqual([]);
});
