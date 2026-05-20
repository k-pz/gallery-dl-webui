import { defineConfig, devices } from "@playwright/test";

// Separate Playwright config that drives the same FakeGallery-backed backend
// the e2e suite uses, but its single "test" is a screen capture pass that
// writes PNGs into ../docs/design/screenshots/.
//
// Run via:
//   pnpm exec playwright test --config=playwright.designshots.config.ts
//
// Different ports + data dir from the regular e2e config so both can run
// side by side without colliding.

const BACKEND_PORT = 8766;
const FRONTEND_PORT = 5175;
const BACKEND_DIR = "../backend";

export default defineConfig({
  testDir: "./designshots",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  timeout: 120_000,
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      name: "backend",
      command: `cd ${BACKEND_DIR} && rm -rf ./data-designshots && PYTHONPATH=. WEBUI_DATA_DIR=./data-designshots WEBUI_PORT=${BACKEND_PORT} uv run uvicorn tests.e2e_server:app --host 127.0.0.1 --port ${BACKEND_PORT} --log-level warning`,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      name: "frontend",
      command: `pnpm vite --port ${FRONTEND_PORT} --strictPort`,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      env: {
        VITE_API_PORT: String(BACKEND_PORT),
      },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
