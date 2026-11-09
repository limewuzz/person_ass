import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
const webBase = process.env.MW_WEB_BASE ?? "/";
if (!/^\/(?:[a-zA-Z0-9_-]+\/)*$/.test(webBase))
  throw Error("MW_WEB_BASE must be a root-relative directory, e.g. / or /app/");
export default defineConfig({
  base: webBase,
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    watch: {
      ignored: [
        "**/evidence/**",
        "**/test-results*/**",
        "**/playwright-report/**",
        "**/.runtime/**",
      ],
    },
    proxy:
      process.env.VITE_API_MODE === "loopback"
        ? {
            "/api": { target: "http://127.0.0.1:8128", changeOrigin: false },
            "/local": { target: "http://127.0.0.1:8128", changeOrigin: false },
          }
        : undefined,
  },
  preview: { host: "127.0.0.1" },
  build: { chunkSizeWarningLimit: 700 },
});
