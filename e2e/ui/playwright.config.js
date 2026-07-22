const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  testMatch: "card.spec.js",
  timeout: 30_000,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["line"], ["junit", { outputFile: "../../artifacts/ha-ui-e2e/junit.xml" }]],
  use: {
    baseURL: process.env.HA_E2E_BASE_URL || "http://127.0.0.1:8123",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium-desktop", use: { browserName: "chromium", viewport: { width: 1280, height: 900 } } },
    { name: "chromium-mobile", use: { browserName: "chromium", viewport: { width: 390, height: 844 } } }
  ],
  outputDir: "../../artifacts/ha-ui-e2e/results",
});
