import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// Browser checks run against real servers on spare ports, with a fresh,
// temporary runtime folder (uploads made by the tests never touch runtime/).
const API_PORT = 8766;
const WEB_PORT = 5174;
const runtime = process.env.E2E_RUNTIME_DIR ?? path.join(os.tmpdir(), `molarmetrics-e2e-${Date.now()}`);

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    channel: "chrome", // the installed Google Chrome: no browser download
    viewport: { width: 1440, height: 1000 },
    acceptDownloads: true,
  },
  webServer: [
    {
      command: `.venv/bin/python -m molarmetrics.api --port ${API_PORT}`,
      cwd: "..",
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      env: { MOLARMETRICS_RUNTIME_DIR: runtime },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npx vite",
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: {
        MOLARMETRICS_API_URL: `http://127.0.0.1:${API_PORT}`,
        MOLARMETRICS_WEB_PORT: String(WEB_PORT),
        MOLARMETRICS_VITE_CACHE: "node_modules/.vite-e2e",
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
