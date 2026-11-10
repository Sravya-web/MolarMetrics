/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Both servers listen on this computer only. The browser talks to the API
// through this proxy (same origin), so the API never needs CORS and the
// local question service is never exposed to the browser directly.
const apiTarget = process.env.MOLARMETRICS_API_URL ?? "http://127.0.0.1:8000";
const port = Number(process.env.MOLARMETRICS_WEB_PORT ?? 5173);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Pre-bundle the heavy libraries at start-up (no mid-session reloads), and let
  // the browser tests use their own cache so two dev servers never collide.
  cacheDir: process.env.MOLARMETRICS_VITE_CACHE ?? "node_modules/.vite",
  optimizeDeps: { include: ["react", "react-dom", "react-dom/client", "recharts", "lucide-react"] },
  server: {
    host: "127.0.0.1",
    port,
    strictPort: true,
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  preview: {
    host: "127.0.0.1",
    port,
    strictPort: true,
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  // Served from this computer only, so one ~700 KB bundle (mostly the chart library) is fine.
  build: { sourcemap: false, chunkSizeWarningLimit: 900 },
  test: { include: ["src/**/*.test.ts"], environment: "node" },
});
