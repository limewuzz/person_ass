import { defineConfig } from "@playwright/test";
export default defineConfig({
  outputDir: "test-results-integration",
  testDir: "integration/browser",
  workers: 1,
  timeout: 60000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: [
    ["list"],
    ["junit", { outputFile: "evidence/live-integration/junit.xml" }],
    [
      "html",
      { open: "never", outputFolder: "evidence/live-integration/report" },
    ],
  ],
});
