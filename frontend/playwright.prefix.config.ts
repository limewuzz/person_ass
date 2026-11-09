import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "integration/prefix",
  outputDir: "test-results-prefix",
  workers: 1,
  timeout: 90000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: [
    ["list"],
    ["junit", { outputFile: "evidence/prefix/junit.xml" }],
    ["html", { open: "never", outputFolder: "evidence/prefix/report" }],
  ],
});
