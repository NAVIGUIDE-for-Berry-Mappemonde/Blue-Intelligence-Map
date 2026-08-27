import axios from "axios";

const backendUrl = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

const api = axios.create({
  // Same-origin preview/deploy works without a build-time backend URL;
  // split deployments can still provide REACT_APP_BACKEND_URL.
  baseURL: `${backendUrl}/api`,
  timeout: 30000,
});

export default api;
