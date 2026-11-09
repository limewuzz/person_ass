import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    reporters: ["default", "junit"],
    outputFile: { junit: "evidence/unit-junit.xml" },
  },
});
