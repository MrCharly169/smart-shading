const SMART_SHADING_SOURCE = /smart[-_\s]+shading/i;

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
