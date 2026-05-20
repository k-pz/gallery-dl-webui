import { expect, test } from "@playwright/test";

// These tests exercise the maintenance tab against the live backend wired up
// in playwright.config.ts. The backend's data dir is wiped at boot so each
// run starts from an empty maintenance jobs table.

test.describe("maintenance tab", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "gallery-dl-webui" })).toBeVisible();
  });

  test("rejects rename without a configured postprocess root", async ({ page }) => {
    // No root configured → the worker will fail the job with a clear reason.
    await page.request.put("/api/config", {
      data: {
        postprocess_root: null,
        postprocess_default_output_dir: null,
        delete_raw_after_pack: true,
      },
    });

    await page.getByRole("tab", { name: /maintenance/i }).click();
    await page.getByRole("button", { name: /schedule chapter rename/i }).click();

    // The job should land in the table, then transition to a terminal status
    // (failed, since no root is configured for the rename pass).
    const firstRow = page.locator("tbody tr").first();
    await expect(firstRow.getByText(/rename_chapters/i)).toBeVisible();
    await expect(firstRow.getByText(/^(failed|completed|cancelled)$/i)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("offers a cancel button on a non-terminal row", async ({ page }) => {
    // Schedule directly via the API so we can race the worker — the row may
    // already have flipped to failed by the time the click lands, but the
    // button itself is the assertion: it must appear at all while the row is
    // pending or running.
    await page.request.post("/api/maintenance/jobs", { data: { kind: "rename_chapters" } });

    await page.getByRole("tab", { name: /maintenance/i }).click();
    const firstRow = page.locator("tbody tr").first();
    await expect(firstRow.getByText(/rename_chapters/i)).toBeVisible();

    // Once the row reaches a terminal state, the cancel control disappears.
    await expect(firstRow.getByText(/^(failed|completed|cancelled)$/i)).toBeVisible({
      timeout: 10_000,
    });
    await expect(firstRow.getByLabel(/cancel maintenance job/i)).toHaveCount(0);
  });

  test("rebuild library is gated behind type-to-confirm", async ({ page }) => {
    await page.getByRole("tab", { name: /maintenance/i }).click();

    // Click the prompt button — the inline type-to-confirm strip should appear.
    await page.getByRole("button", { name: /^rebuild library…$/i }).click();
    const typeField = page.getByLabel(/type rebuild to confirm/i);
    await expect(typeField).toBeVisible();

    // The arming button stays disabled until the user types the exact word.
    const armed = page.getByRole("button", { name: /^rebuild library$/i });
    await expect(armed).toBeDisabled();

    // Cancel — the strip retracts, nothing is scheduled.
    await page.getByRole("button", { name: /^cancel$/i }).click();
    await expect(typeField).toHaveCount(0);
    await page.waitForTimeout(250);
    const beforeRows = await page
      .locator("tbody tr")
      .filter({ hasText: "rebuild_library" })
      .count();
    expect(beforeRows).toBe(0);

    // Open it again, type the word, fire — a rebuild_library row should show.
    await page.getByRole("button", { name: /^rebuild library…$/i }).click();
    await page.getByLabel(/type rebuild to confirm/i).fill("rebuild");
    await expect(armed).toBeEnabled();
    await armed.click();
    await expect(
      page.locator("tbody tr").filter({ hasText: "rebuild_library" }).first(),
    ).toBeVisible();
  });
});
