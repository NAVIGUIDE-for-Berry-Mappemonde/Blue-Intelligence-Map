import axios from "axios";

// URL du backend : REACT_APP_BACKEND_URL si définie, sinon même origine
// (le proxy CRA route /api vers localhost:8001 en dev ; en production le
// reverse proxy sert /api/* — voir README).
export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";

const api = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  timeout: 120000,
});

export default api;
