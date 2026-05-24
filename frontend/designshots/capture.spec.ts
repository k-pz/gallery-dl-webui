import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Seeds the FakeGallery-backed backend with a handful of jobs and snaps every
// tab in both color schemes. Output PNGs land in docs/design/screenshots/.
//
// Run via:
//   pnpm exec playwright test --config=playwright.designshots.config.ts

const OK_URL = "https://e2e.test/ok";
const SLOW_URL = "https://e2e.test/very-slow";
const UNSUPPORTED_URL = "https://e2e.test/unsupported";
const BACKEND = "http://127.0.0.1:8766";

const OUTPUT_DIR = path.resolve(__dirname, "..", "..", "docs", "design", "screenshots");
fs.mkdirSync(OUTPUT_DIR, { recursive: true });

const THEMES = ["light", "dark"] as const;
type Theme = (typeof THEMES)[number];

test.describe.configure({ mode: "serial" });

test("empty states, both themes", async ({ page }) => {
  test.setTimeout(60_000);
  for (const theme of THEMES) {
    await setTheme(page, theme);
    await page.goto("/");
    await disableStickyHeader(page);
    await page.getByRole("tab", { name: "Library" }).click();
    await waitForIdle(page);
    await snap(page, `01-library-empty-${theme}`);

    await page.getByRole("tab", { name: "Jobs" }).click();
    await waitForIdle(page);
    await snap(page, `02-jobs-empty-${theme}`);

    await page.getByRole("tab", { name: "Config" }).click();
    await waitForIdle(page);
    await snap(page, `03-config-${theme}`);

    await page.getByRole("tab", { name: "Maintenance" }).click();
    await waitForIdle(page);
    await snap(page, `04-maintenance-empty-${theme}`);
  }
});

test("populated states, both themes", async ({ page, request }) => {
  test.setTimeout(120_000);

  await seedConfig(request);
  // OK URL → fast completion, gets a library row + a completed job row.
  await request.post(`${BACKEND}/api/downloads`, {
    data: { url: OK_URL, watched: true, tags: ["action", "shounen"] },
  });
  await waitForCompleted(request, 1);

  // Unsupported URL → adds a "failed" job row.
  await request.post(`${BACKEND}/api/downloads`, { data: { url: UNSUPPORTED_URL } });

  // Schedule a maintenance job so the Maintenance tab has history.
  await request.post(`${BACKEND}/api/maintenance/jobs`, {
    data: { kind: "rename_chapters" },
  });

  // Once configured screens are seeded, capture per theme — re-submitting the
  // slow URL each iteration so the Jobs tab always has an in-flight job.
  for (const theme of THEMES) {
    await setTheme(page, theme);
    // Re-trigger a slow download so the next 3-4 screenshots have an active
    // job to render.
    await request.post(`${BACKEND}/api/downloads`, { data: { url: SLOW_URL } });
    await waitForRunning(request);

    await page.goto("/");
    await disableStickyHeader(page);
    await page.getByRole("tab", { name: "Library" }).click();
    await waitForIdle(page);
    await snap(page, `05-library-populated-${theme}`);

    await page.getByRole("tab", { name: "Jobs" }).click();
    // Wait briefly for the running row to render, then click the most recent
    // one (which should be the slow URL).
    await page
      .locator(".app-row")
      .first()
      .waitFor({ state: "visible", timeout: 8_000 })
      .catch(() => {
        /* if nothing's running anymore, the captured shot still works */
      });
    const slowRow = page.locator(".app-row", { hasText: "/very-slow" }).first();
    await slowRow.click({ timeout: 3_000 }).catch(() => {
      /* no slow row visible, skip */
    });
    await waitForIdle(page);
    await snap(page, `06-jobs-active-${theme}`);

    // Show all statuses so the badges for failed/completed/cancelled appear
    // alongside the active one. Scope by the visible Tabs.Panel so the click
    // doesn't land on the Library tab's same-named Select.
    const visiblePanel = page.locator('.mantine-Tabs-panel[role="tabpanel"]:not([hidden])');
    await visiblePanel
      .getByRole("combobox", { name: "Status" })
      .click({ timeout: 3_000 })
      .catch(() => {});
    await page
      .getByRole("option", { name: "Any" })
      .click({ timeout: 2_000 })
      .catch(() => {});
    await waitForIdle(page);
    await snap(page, `08-jobs-all-statuses-${theme}`);

    await page.getByRole("tab", { name: "Maintenance" }).click();
    await waitForIdle(page);
    await snap(page, `09-maintenance-populated-${theme}`);
  }

  expect(true).toBe(true);
});

async function seedConfig(request: APIRequestContext) {
  const root = "/tmp/gallery-dl-designshots-root";
  const defaultDir = `${root}/manga`;
  fs.mkdirSync(defaultDir, { recursive: true });
  await request.put(`${BACKEND}/api/config`, {
    data: {
      postprocess_root: root,
      postprocess_default_output_dir: defaultDir,
      delete_raw_after_pack: true,
      default_watch_period: "1d",
      chapter_naming_template: "",
      default_reading_direction: "ltr",
      postprocess_excluded_dir_names: ["#recycle", "@eaDir"],
      max_parallel_postprocess: 3,
    },
  });
}

async function setTheme(page: Page, theme: Theme) {
  await page.addInitScript((t) => {
    try {
      window.localStorage.setItem("mantine-color-scheme-value", t);
    } catch {
      /* noop */
    }
    document.documentElement.setAttribute("data-mantine-color-scheme", t);
  }, theme);
}

async function disableStickyHeader(page: Page) {
  // fullPage screenshots in Chromium pin position:sticky elements where they
  // were on the initial paint — without this they show up twice in tall
  // captures. Injected per-page, after navigation.
  await page.addStyleTag({
    content: ".app-shell-header { position: static !important; }",
  });
}

async function waitForIdle(page: Page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(400);
}

async function snap(page: Page, name: string) {
  await page.screenshot({
    path: path.join(OUTPUT_DIR, `${name}.png`),
    fullPage: true,
  });
}

async function waitForCompleted(request: APIRequestContext, expected: number) {
  for (let i = 0; i < 50; i++) {
    const res = await request.get(`${BACKEND}/api/downloads`);
    const list = (await res.json()) as Array<{ status: string }>;
    const completed = list.filter((d) => d.status === "completed").length;
    if (completed >= expected) return;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error("timeout waiting for a completed download");
}

async function waitForRunning(request: APIRequestContext) {
  for (let i = 0; i < 40; i++) {
    const res = await request.get(`${BACKEND}/api/downloads`);
    const list = (await res.json()) as Array<{ status: string }>;
    if (list.some((d) => d.status === "running" || d.status === "extracting")) return;
    await new Promise((r) => setTimeout(r, 150));
  }
}
