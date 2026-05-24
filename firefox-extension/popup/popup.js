import { api, apiErrorMessage } from "../lib/api.js";
import { loadSettings, normalizeBackendUrl } from "../lib/storage.js";

const el = (id) => document.getElementById(id);
const show = (id) => el(id).classList.remove("hidden");
const hide = (id) => el(id).classList.add("hidden");

let backendUrl = "";

async function getActiveTabUrl() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  return tabs[0]?.url ?? "";
}

function openOptions(e) {
  if (e) e.preventDefault();
  browser.runtime.openOptionsPage();
}

function showFatal(message) {
  hide("loading");
  hide("add-form");
  hide("setup-needed");
  hide("success");
  el("backend-error-msg").textContent = message;
  show("backend-error");
}

function splitTags(raw) {
  return raw
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

async function init() {
  el("open-options").addEventListener("click", openOptions);
  el("open-options-cta").addEventListener("click", openOptions);
  el("retry").addEventListener("click", () => {
    hide("backend-error");
    show("loading");
    init();
  });
  el("add-another").addEventListener("click", () => {
    hide("success");
    show("add-form");
    el("url").focus();
  });
  el("add-form").addEventListener("submit", onSubmit);

  const settings = await loadSettings();
  backendUrl = normalizeBackendUrl(settings.backendUrl);
  if (!backendUrl) {
    hide("loading");
    show("setup-needed");
    return;
  }

  try {
    const [config, dirs, activeUrl] = await Promise.all([
      api.getConfig(backendUrl),
      api.listOutputDirs(backendUrl).catch(() => []),
      getActiveTabUrl(),
    ]);
    populateForm({ config, dirs, activeUrl });
    hide("loading");
    show("add-form");
    el("url").focus();
    el("url").select();
  } catch (err) {
    showFatal(`Could not reach ${backendUrl}: ${apiErrorMessage(err)}`);
  }
}

function populateForm({ config, dirs, activeUrl }) {
  el("url").value = activeUrl || "";

  const datalist = el("output-dir-options");
  datalist.innerHTML = "";
  const seen = new Set();
  const addOption = (path) => {
    if (!path || seen.has(path)) return;
    seen.add(path);
    const opt = document.createElement("option");
    opt.value = path;
    datalist.appendChild(opt);
  };
  if (config?.postprocess_default_output_dir) addOption(config.postprocess_default_output_dir);
  for (const d of dirs || []) addOption(d.path);
  for (const k of config?.postprocess_known_output_dirs || []) addOption(k);

  const outputDir = el("output-dir");
  if (config?.postprocess_default_output_dir) {
    outputDir.value = config.postprocess_default_output_dir;
  }
  if (!config?.postprocess_root) {
    outputDir.disabled = true;
    outputDir.placeholder = "Set a root in Config first";
    el("output-dir-hint").textContent = "Postprocessing disabled until a root is configured.";
  } else {
    el("output-dir-hint").textContent = `Must be under root: ${config.postprocess_root}`;
  }

  const direction = el("reading-direction");
  if (config?.default_reading_direction) {
    direction.value = config.default_reading_direction;
  }
}

async function onSubmit(e) {
  e.preventDefault();
  const submit = el("submit");
  const errBox = el("form-error");
  hide("form-error");

  const url = el("url").value.trim();
  if (!url) {
    errBox.textContent = "URL is required.";
    show("form-error");
    return;
  }

  const outputDir = el("output-dir").value.trim();
  const tags = splitTags(el("tags").value);
  const direction = el("reading-direction").value;
  const watched = el("watched").checked;

  const payload = {
    url,
    output_dir: outputDir || null,
    watched,
    tags: tags.length > 0 ? tags : null,
    reading_direction: direction || null,
  };

  submit.disabled = true;
  submit.textContent = "Adding…";
  try {
    const created = await api.createDownload(backendUrl, payload);
    hide("add-form");
    el("success-name").textContent = created.name
      ? `${created.name} (job #${created.id})`
      : `Job #${created.id} queued`;
    el("view-link").href = backendUrl;
    show("success");
  } catch (err) {
    errBox.textContent = apiErrorMessage(err);
    show("form-error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Add";
  }
}

init();
