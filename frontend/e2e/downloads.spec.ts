import { expect, test } from "@playwright/test";

// These URLs are seeded inside backend/tests/e2e_server.py.
const OK_URL = "https://e2e.test/ok";
const SLOW_URL = "https://e2e.test/slow";
const UNSUPPORTED_URL = "https://e2e.test/unsupported";

test.describe("downloads UI", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "gallery-dl-webui" })).toBeVisible();
    // The health badge sits next to the "backend" label.
    const badge = page.getByText("backend").locator("..").getByText("ok", { exact: true });
    await expect(badge).toBeVisible();
  });

  test("submits a URL and shows it completed in the recent list", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill(OK_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    // Submit doesn't auto-select. Switch to the Jobs tab and click the row
    // that just landed to open it in the active-job card.
    await openJobByUrl(page, OK_URL);

    // The progress card reports all chapters settled once the worker is done.
    // OK_URL has 2 chapters in its manifest.
    await expect(page.getByText(/2\s*\/\s*2\s+chapters/i)).toBeVisible({ timeout: 15_000 });
  });

  test("rejects an unsupported URL inline", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill(UNSUPPORTED_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    // The error surfaces in two places — inline under the form *and* in the
    // notification. Either is enough to confirm rejection.
    await expect(page.getByText(/unsupported URL/i).first()).toBeVisible();
  });

  test("validates blank input before hitting the backend", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill("   ");
    await page.getByRole("button", { name: /^download$/i }).click();

    await expect(page.getByText(/enter a gallery url\./i)).toBeVisible();
  });

  test("shows live progress for a slow download", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill(SLOW_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    await openJobByUrl(page, SLOW_URL);

    // ProgressCard reports the single chapter settled once download wraps up.
    // SLOW_URL has 1 chapter ("slow") with 5 files.
    await expect(page.getByText(/1\s*\/\s*1\s+chapters/i)).toBeVisible({ timeout: 30_000 });
  });

  test("cancels a slow download from the active job card", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill(SLOW_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    await openJobByUrl(page, SLOW_URL);

    // The active card's Cancel button (textual, not the row icon) is only
    // visible while the job is non-terminal.
    const cancelBtn = activeJobButton(page, /^cancel$/i);
    await expect(cancelBtn).toBeVisible({ timeout: 10_000 });
    await cancelBtn.click();

    // Once cancelled, the active card swaps Cancel for Requeue and the
    // solid pill that replaces the stepper reads "Cancelled".
    await expect(activeJobButton(page, /^requeue$/i)).toBeVisible({ timeout: 15_000 });
    await expect(
      page
        .locator(".pill")
        .getByText(/^cancelled$/i)
        .first(),
    ).toBeVisible();
  });

  test("requeues a completed download back to running", async ({ page }) => {
    // SLOW_URL on purpose — OK_URL completes in <100ms and a requeued run
    // would finish before we can observe the intermediate non-terminal state.
    await page.getByLabel(/gallery url/i).fill(SLOW_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    await openJobByUrl(page, SLOW_URL);

    // Wait for completion of the first run. ActiveJobCard hides the Cancel
    // button (and shows Requeue) only on a terminal state — both signals
    // together rule out a racy "we caught it mid-stepper-paint" false read.
    await expect(page.getByText(/1\s*\/\s*1\s+chapters/i)).toBeVisible({ timeout: 30_000 });
    await expect(activeJobButton(page, /^requeue$/i)).toBeVisible();

    // Click Requeue and watch the active card return to a non-terminal state.
    await activeJobButton(page, /^requeue$/i).click();
    await expect(activeJobButton(page, /^cancel$/i)).toBeVisible({ timeout: 10_000 });

    // It should complete again — Requeue returns once it's terminal.
    await expect(activeJobButton(page, /^requeue$/i)).toBeVisible({ timeout: 30_000 });
  });
});

// --- helpers ----------------------------------------------------------------

async function openJobByUrl(page: import("@playwright/test").Page, url: string) {
  // Switch to Jobs and click the row whose name/URL matches. Default filter
  // is "Active"; a fast job (OK_URL) can complete before we click and would
  // then be hidden — flip to "Any" first so terminal jobs show too.
  await page.getByRole("tab", { name: /^Jobs/i }).click();

  // Mantine keepMounted leaves the Library panel in the DOM with both a
  // "Status" select of its own; scope the filter change to the visible Jobs
  // panel via the Card that contains the Recent list.
  const recentCard = page
    .locator(".mantine-Card-root")
    .filter({ has: page.getByText(/^Jobs$/, { exact: true }) })
    .last();
  await recentCard.getByRole("combobox", { name: /status/i }).click();
  // force:true — the Mantine popover is still animating, so Playwright's
  // stability check fails and the option detaches mid-retry as it repositions.
  await page.getByRole("option", { name: /^any$/i }).click({ force: true });

  const row = page.locator(".app-row", { hasText: url }).first();
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.click();
}

function activeJobButton(page: import("@playwright/test").Page, name: RegExp) {
  // Buttons inside the active-job card are textual (size="xs", variant="light")
  // — the row-level cancel/requeue are ActionIcons with aria-labels like
  // "Cancel #3". Filtering by role=button + name keeps us on the card.
  return page
    .locator(".mantine-Card-root", { has: page.getByText(/active job/i) })
    .getByRole("button", { name });
}
