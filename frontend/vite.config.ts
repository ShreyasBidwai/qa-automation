import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies backend calls so the browser stays same-origin
// (no CORS). In compose the backend is reachable as the `backend` service;
// for host-only dev, override with BACKEND_PROXY_TARGET=http://localhost:8000.
const proxyTarget = process.env.BACKEND_PROXY_TARGET ?? "http://backend:8000";
const proxy = { target: proxyTarget, changeOrigin: true };

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      "/healthz": proxy,
      "/readyz": proxy,
      "/api": proxy,
    },
  },
});
