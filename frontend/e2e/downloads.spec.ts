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
    const input = page.getByLabel(/gallery url/i);
    await input.fill(OK_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    // The submitted URL appears in the active job card.
    await expect(page.getByTitle(OK_URL).first()).toBeVisible();

    // Active job header reports the final file count once the worker is done.
    await expect(page.getByText(/files:\s*3\s*\/\s*3/i)).toBeVisible({ timeout: 15_000 });
  });

  test("rejects an unsupported URL inline", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill(UNSUPPORTED_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    await expect(page.getByText(/unsupported URL/i)).toBeVisible();
  });

  test("validates blank input before hitting the backend", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill("   ");
    await page.getByRole("button", { name: /^download$/i }).click();

    await expect(page.getByText(/url is required/i)).toBeVisible();
  });

  test("shows live progress for a slow download", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill(SLOW_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    // Active job card appears with the slow URL.
    await expect(page.getByTitle(SLOW_URL).first()).toBeVisible();

    // The job header eventually reports 5 / 5 files.
    await expect(page.getByText(/files:\s*5\s*\/\s*5/i)).toBeVisible({ timeout: 30_000 });

    // ProgressCard's own aggregate must also reach 5 / 5 — guards against the
    // freeze where polling stopped before the final progress fetch landed.
    await expect(page.getByText(/5\s*\/\s*5\s+files/i)).toBeVisible({ timeout: 30_000 });
  });

  test("cancels a slow download from the active job card", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill(SLOW_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    // Wait for the slow URL to appear in the active job card.
    await expect(page.getByTitle(SLOW_URL).first()).toBeVisible();

    // The Cancel button is only visible while the job is non-terminal.
    const cancelBtn = page.getByRole("button", { name: /^cancel$/i });
    await expect(cancelBtn).toBeVisible({ timeout: 10_000 });
    await cancelBtn.click();

    // Once cancelled, the active card swaps Cancel for Requeue and the badge
    // turns into "cancelled".
    await expect(page.getByRole("button", { name: /^requeue$/i }).first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page
        .locator(".mantine-Badge-root")
        .getByText(/^cancelled$/i)
        .first(),
    ).toBeVisible();
  });

  test("requeues a completed download back to running", async ({ page }) => {
    await page.getByLabel(/gallery url/i).fill(OK_URL);
    await page.getByRole("button", { name: /^download$/i }).click();

    // Wait for completion of the first run.
    await expect(page.getByText(/files:\s*3\s*\/\s*3/i)).toBeVisible({ timeout: 15_000 });
    await expect(
      page
        .locator(".mantine-Badge-root")
        .getByText(/^completed$/i)
        .first(),
    ).toBeVisible();

    // Click Requeue and watch the badge return to a non-terminal state.
    await page.getByRole("button", { name: /^requeue$/i }).click();
    const badge = page.locator(".mantine-Badge-root").first();
    await expect(badge).not.toHaveText(/completed/i, { timeout: 5_000 });

    // It should complete again.
    await expect(
      page
        .locator(".mantine-Badge-root")
        .getByText(/^completed$/i)
        .first(),
    ).toBeVisible({
      timeout: 15_000,
    });
  });
});
