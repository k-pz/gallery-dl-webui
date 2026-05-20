import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

let outputDir = "";

test.beforeAll(() => {
  // realpathSync collapses macOS's /var → /private/var symlink up front so the
  // value we feed the form matches the resolved path the backend persists.
  outputDir = realpathSync(mkdtempSync(join(tmpdir(), "gdl-webui-e2e-")));
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

  test("saves the postprocess root and persists across reload", async ({ page }) => {
    await page.getByRole("tab", { name: /config/i }).click();

    const root = page.getByRole("textbox", { name: /^root$/i });
    await expect(root).toBeVisible();
    await expect(root).toHaveValue("");

    await root.fill(outputDir);
    await page.getByLabel(/delete raw images after packing/i).uncheck();
    await page.getByRole("button", { name: /save/i }).click();

    await expect(page.getByText(/^saved\.$/i)).toBeVisible();

    // Reload and confirm the values persist.
    await page.reload();
    await page.getByRole("tab", { name: /config/i }).click();
    await expect(page.getByRole("textbox", { name: /^root$/i })).toHaveValue(outputDir);
    await expect(page.getByLabel(/delete raw images after packing/i)).not.toBeChecked();
  });

  test("rejects a relative root with a clear error", async ({ page }) => {
    await page.getByRole("tab", { name: /config/i }).click();
    await page.getByRole("textbox", { name: /^root$/i }).fill("relative/dir");
    await page.getByRole("button", { name: /save/i }).click();

    // The validation error is rendered inside a Mantine Alert; scope to it so
    // we don't match the field's own "absolute path" description text.
    await expect(page.getByRole("alert")).toContainText(/absolute path/i);
  });

  test("persists the excluded directory names across reload", async ({ page }) => {
    await page.getByRole("tab", { name: /config/i }).click();

    const excluded = page.getByLabel(/excluded directory names/i);
    await expect(excluded).toBeVisible();
    await excluded.fill("#recycle, @eaDir, .Trash");
    await page.getByRole("button", { name: /save/i }).click();
    await expect(page.getByText(/^saved\.$/i)).toBeVisible();

    await page.reload();
    await page.getByRole("tab", { name: /config/i }).click();
    await expect(page.getByLabel(/excluded directory names/i)).toHaveValue(
      "#recycle, @eaDir, .Trash",
    );
  });
});
