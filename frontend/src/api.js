import axios from "axios";

// URL du backend : REACT_APP_BACKEND_URL si définie, sinon même origine
// (le proxy CRA route /api vers localhost:8001 en dev ; en production le
// reverse proxy sert /api/* — voir README).
export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";

// ---------------------------------------------------------------------------
// Mode admin — ouvrir l'app avec `?admin=<clé>` mémorise la clé (localStorage)
// et l'envoie ensuite dans le header X-Admin-Key ; `?admin=off` la retire.
// Les onglets Console / Review ne s'affichent que si le backend valide la clé
// (GET /admin/check). Le paramètre est retiré de l'URL après lecture.
// ---------------------------------------------------------------------------
const ADMIN_STORAGE_KEY = "bi.adminKey";

function bootstrapAdminKey() {
  try {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("admin");
    if (fromUrl !== null) {
      if (fromUrl === "" || fromUrl === "off") {
        localStorage.removeItem(ADMIN_STORAGE_KEY);
      } else {
        localStorage.setItem(ADMIN_STORAGE_KEY, fromUrl);
      }
      params.delete("admin");
      const qs = params.toString();
      window.history.replaceState(
        {}, "",
        window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash,
      );
    }
    return localStorage.getItem(ADMIN_STORAGE_KEY) || "";
  } catch (_) {
    return "";
  }
}

const adminKey = bootstrapAdminKey();

export function hasAdminKey() {
  return Boolean(adminKey);
}

export function clearAdminKey() {
  try { localStorage.removeItem(ADMIN_STORAGE_KEY); } catch (_) { /* ignore */ }
}

const api = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  timeout: 120000,
  ...(adminKey ? { headers: { "X-Admin-Key": adminKey } } : {}),
});

export default api;
