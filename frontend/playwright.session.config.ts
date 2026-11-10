import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "integration/session",
  outputDir: "test-results-session",
  workers: 1,
  timeout: 30000,
  use: { serviceWorkers: "block", screenshot: "only-on-failure" },
  reporter: [["list"], ["junit", { outputFile: "evidence/session/junit.xml" }]],
});
