import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
const here = fileURLToPath(new URL(".", import.meta.url));
export default defineConfig({
  root: resolve(here, "portal"),
  base: "/",
  publicDir: false,
  plugins: [react()],
  build: {
    outDir: resolve(here, "dist-portal"),
    emptyOutDir: true,
    assetsDir: "portal-assets",
    chunkSizeWarningLimit: 700,
  },
});
