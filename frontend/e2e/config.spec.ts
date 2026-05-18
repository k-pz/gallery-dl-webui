import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

let outputDir = "";

test.beforeAll(() => {
  outputDir = mkdtempSync(join(tmpdir(), "gdl-webui-e2e-"));
});

test.afterAll(() => {
  if (outputDir) {
    rmSync(outputDir, { recursive: true, force: true });
  }
});

test.describe("config tab", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "gallery-dl-webui" })).toBeVisible();
    // Reset the persisted config before each test.
    await page.request.put("/api/config", {
      data: { postprocess_output_dir: null, delete_raw_after_pack: true },
    });
  });

  test("saves the output directory and persists across reload", async ({ page }) => {
    await page.getByRole("tab", { name: /config/i }).click();

    const input = page.getByLabel(/output directory/i);
    await expect(input).toBeVisible();
    await expect(input).toHaveValue("");

    await input.fill(outputDir);
    await page.getByLabel(/delete raw images after packing/i).uncheck();
    await page.getByRole("button", { name: /save/i }).click();

    await expect(page.getByText(/^saved\.$/i)).toBeVisible();

    // Reload and confirm the values persist.
    await page.reload();
    await page.getByRole("tab", { name: /config/i }).click();
    await expect(page.getByLabel(/output directory/i)).toHaveValue(outputDir);
    await expect(page.getByLabel(/delete raw images after packing/i)).not.toBeChecked();
  });

  test("rejects a relative path with a clear error", async ({ page }) => {
    await page.getByRole("tab", { name: /config/i }).click();
    await page.getByLabel(/output directory/i).fill("relative/dir");
    await page.getByRole("button", { name: /save/i }).click();

    // The validation error is rendered inside a Mantine Alert; scope to it so
    // we don't match the field's own "absolute path" description text.
    await expect(page.getByRole("alert")).toContainText(/absolute path/i);
  });
});
