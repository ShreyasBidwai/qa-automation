import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Bind to 0.0.0.0 so the dev server is reachable from outside the container.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
  },
});
