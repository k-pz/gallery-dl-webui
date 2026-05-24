export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Pull a user-facing message from a thrown value — ApiError keeps its own
 *  message; anything else falls back to String(err). */
export function apiErrorMessage(err) {
  return err instanceof ApiError ? err.message : String(err);
}

async function request(backendUrl, method, path, body) {
  if (!backendUrl) {
    throw new ApiError("Backend URL is not configured. Open the extension options to set it.");
  }
  const url = `${backendUrl}/api${path}`;
  const init = {
    method,
    headers: { Accept: "application/json" },
  };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    throw new ApiError(`Network error: ${err.message}`);
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      // Non-JSON error pages from a proxy etc.
    }
  }
  if (!response.ok) {
    const detail = (data && (data.detail || data.message)) || text || response.statusText;
    throw new ApiError(detail || `HTTP ${response.status}`, response.status);
  }
  return data;
}

export const api = {
  getConfig: (backendUrl) => request(backendUrl, "GET", "/config"),
  listOutputDirs: (backendUrl) => request(backendUrl, "GET", "/output-dirs"),
  health: (backendUrl) => request(backendUrl, "GET", "/health"),
  createDownload: (backendUrl, payload) => request(backendUrl, "POST", "/downloads", payload),
};
