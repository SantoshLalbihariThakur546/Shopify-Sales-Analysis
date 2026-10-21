// Backend location. Empty string = same origin (Flask serves this page).
// Only change it if you open the frontend from a different server, e.g.
//   API_BASE: "http://127.0.0.1:5000"   (and start the backend with CORS_ORIGINS=<that origin>)
export const CONFIG = {
  API_BASE: "",
  DEBOUNCE_MS: 120,
};
