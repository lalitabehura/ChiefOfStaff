import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Same-origin API in dev keeps the SameSite=Strict refresh cookie working.
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: false } },
  },
  build: { sourcemap: false },
});
