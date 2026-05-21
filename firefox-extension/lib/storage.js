const SETTINGS_KEY = "settings";

const DEFAULTS = {
  backendUrl: "",
};

export async function loadSettings() {
  const stored = await browser.storage.local.get(SETTINGS_KEY);
  const raw = stored[SETTINGS_KEY] || {};
  return { ...DEFAULTS, ...raw };
}

export async function saveSettings(patch) {
  const current = await loadSettings();
  const next = { ...current, ...patch };
  await browser.storage.local.set({ [SETTINGS_KEY]: next });
  return next;
}

export function normalizeBackendUrl(raw) {
  const trimmed = (raw || "").trim().replace(/\/+$/, "");
  return trimmed;
}
