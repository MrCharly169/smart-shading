const SMART_SHADING_SOURCE = /smart[-_\s]+shading/i;
const FIXTURE_BRAND_ICON =
  /\/api\/brands\/integration\/smart_shading_test_fixture\/icon\.png(?:\?|$)/i;

function referencesSmartShading(...values) {
  return values.some(
    (value) => typeof value === "string" && SMART_SHADING_SOURCE.test(value)
  );
}

function captureSmartShadingBrowserErrors(page) {
  const errors = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const text = message.text();
    const source = message.location()?.url || "";
    if (/404 \(Not Found\)/i.test(text) && FIXTURE_BRAND_ICON.test(source)) {
      return;
    }
    if (referencesSmartShading(text, source)) {
      errors.push(source ? `${text} (${source})` : text);
    }
  });
  page.on("pageerror", (error) => {
    const text = String(error);
    const stack = typeof error?.stack === "string" ? error.stack : "";
    if (referencesSmartShading(text, stack)) errors.push(stack || text);
  });
  return errors;
}

module.exports = {
  captureSmartShadingBrowserErrors,
  referencesSmartShading,
};
