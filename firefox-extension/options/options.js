import { api, ApiError } from "../lib/api.js";
import { loadSettings, normalizeBackendUrl, saveSettings } from "../lib/storage.js";

const el = (id) => document.getElementById(id);

function setStatus(kind, text) {
  const status = el("status");
  status.textContent = text;
  status.classList.remove("hidden", "success", "error");
  if (kind) status.classList.add(kind);
}

function clearStatus() {
  el("status").classList.add("hidden");
}

async function init() {
  el("self-origin").textContent = location.origin;
  const settings = await loadSettings();
  el("backend-url").value = settings.backendUrl || "";

  el("options-form").addEventListener("submit", onSave);
  el("test").addEventListener("click", onTest);
}

async function onSave(e) {
  e.preventDefault();
  const raw = normalizeBackendUrl(el("backend-url").value);
  if (!raw) {
    setStatus("error", "Backend URL is required.");
    return;
  }
  await saveSettings({ backendUrl: raw });
  el("backend-url").value = raw;
  setStatus("success", "Saved.");
}

async function onTest() {
  clearStatus();
  const raw = normalizeBackendUrl(el("backend-url").value);
  if (!raw) {
    setStatus("error", "Enter a backend URL first.");
    return;
  }
  const btn = el("test");
  btn.disabled = true;
  try {
    await api.health(raw);
    setStatus("success", `OK — ${raw} responded.`);
  } catch (err) {
    const msg = err instanceof ApiError ? err.message : String(err);
    setStatus("error", `Failed: ${msg}`);
  } finally {
    btn.disabled = false;
  }
}

init();
