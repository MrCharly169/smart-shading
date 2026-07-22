const assert = require("assert");
const {
  captureSmartShadingBrowserErrors,
  referencesSmartShading,
} = require("../e2e/ui/browser-errors");

assert.strictEqual(
  referencesSmartShading("Object", "http://ha.local/frontend_latest/app.js"),
  false
);
assert.strictEqual(
  referencesSmartShading(
    "Failed to load favorites: TypeError: Failed to fetch",
    "http://ha.local/frontend_latest/app.js"
  ),
  false
);
assert.strictEqual(
  referencesSmartShading(
    "Object",
    "http://ha.local/smart_shading/shading.js"
  ),
  true
);
assert.strictEqual(
  referencesSmartShading("Smart Shading card failed", ""),
  true
);

const handlers = {};
const page = {
  on(event, handler) {
    handlers[event] = handler;
  },
};
const errors = captureSmartShadingBrowserErrors(page);

handlers.console({
  type: () => "error",
  text: () => "Object",
  location: () => ({ url: "http://ha.local/frontend_latest/app.js" }),
});
handlers.pageerror(
  Object.assign(new Error("Failed to load favorites"), {
    stack: "Error: Failed to load favorites\n at http://ha.local/frontend_latest/app.js:1:1",
  })
);
assert.deepStrictEqual(errors, []);

handlers.console({
  type: () => "error",
  text: () => "Card rendering failed",
  location: () => ({ url: "http://ha.local/smart_shading/shading.js" }),
});
handlers.pageerror(
  Object.assign(new Error("Custom element failed"), {
    stack: "Error: Custom element failed\n at http://ha.local/smart_shading/shading.js:2:3",
  })
);
assert.strictEqual(errors.length, 2);
assert.ok(errors.every((error) => error.includes("smart_shading")));

console.log("Browser error attribution checks passed");
