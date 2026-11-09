import { defineConfig } from "@playwright/test";
export default defineConfig({
  outputDir: "test-results-mock",
  testDir: "e2e",
  timeout: 60000,
  workers: 2,
  retries: 0,
  reporter: [
    ["list"],
    ["junit", { outputFile: "evidence/e2e-junit.xml" }],
    ["html", { open: "never", outputFolder: "evidence/playwright-report" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: false,
    timeout: 60000,
  },
});
