const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  testMatch: "card.spec.js",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [["line"], ["junit", { outputFile: "../../artifacts/ha-ui-e2e/junit.xml" }]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "retain-on-failure",
  },
  webServer: {
    command: "python3 -m http.server 4173 --bind 127.0.0.1 --directory ../..",
    url: "http://127.0.0.1:4173/e2e/ui/harness.html",
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    { name: "chromium-desktop", use: { browserName: "chromium", viewport: { width: 1280, height: 900 } } },
    { name: "chromium-mobile", use: { browserName: "chromium", viewport: { width: 390, height: 844 } } }
  ],
  outputDir: "../../artifacts/ha-ui-e2e/results",
});
