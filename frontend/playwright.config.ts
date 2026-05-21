import { defineConfig, devices } from "@playwright/test";

const BACKEND_PORT = 8765;
const FRONTEND_PORT = 5174;
const BACKEND_DIR = "../backend";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? "dot" : "list",
  use: {
    baseURL: `http://127.0.0.1:${FRONTEND_PORT}`,
    trace: "on-first-retry",
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
      command: `cd ${BACKEND_DIR} && rm -rf ./data-e2e && PYTHONPATH=. WEBUI_DATA_DIR=./data-e2e WEBUI_PORT=${BACKEND_PORT} uv run uvicorn tests.e2e_server:app --host 127.0.0.1 --port ${BACKEND_PORT} --log-level warning`,
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      // Reuse a server that's already on the port (CI boots them itself
      // before invoking playwright; local dev typically has `mise run dev`
      // running). Playwright still starts one if the port is free.
      reuseExistingServer: true,
      // CI runners cold-start the backend venv + import a large FastAPI app
      // for the first time, which routinely takes longer than the local
      // dev-loop budget. Local devs already have warm caches.
      timeout: process.env.CI ? 120_000 : 30_000,
    },
    {
      name: "frontend",
      command: `pnpm vite --port ${FRONTEND_PORT} --strictPort`,
      url: `http://127.0.0.1:${FRONTEND_PORT}`,
      env: {
        VITE_API_PORT: String(BACKEND_PORT),
      },
      // Reuse a server that's already on the port (CI boots them itself
      // before invoking playwright; local dev typically has `mise run dev`
      // running). Playwright still starts one if the port is free.
      reuseExistingServer: true,
      // See backend webServer above — CI cold-start budget.
      timeout: process.env.CI ? 120_000 : 30_000,
    },
  ],
});
