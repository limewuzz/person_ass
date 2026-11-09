import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
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
