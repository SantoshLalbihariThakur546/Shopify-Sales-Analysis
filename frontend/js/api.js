// Thin client for the Flask API.
import { CONFIG } from "./config.js";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function getJSON(path, params, signal) {
  const query = params && params.toString() ? `?${params.toString()}` : "";
  let response;
  try {
    response = await fetch(`${CONFIG.API_BASE}${path}${query}`, {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(
      "Cannot reach the backend. Make sure it is running (python run.py) and refresh this page.",
    );
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* non-JSON error page */
  }
  if (!response.ok) {
    throw new ApiError(body?.error || `The server returned an error (HTTP ${response.status}).`, response.status);
  }
  return body;
}
