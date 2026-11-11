import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "integration/us",
  outputDir: "test-results-us",
  workers: 1,
  timeout: 30000,
  use: { trace: "retain-on-failure", screenshot: "only-on-failure" },
  reporter: [["list"], ["junit", { outputFile: "evidence/us/junit.xml" }]],
});
