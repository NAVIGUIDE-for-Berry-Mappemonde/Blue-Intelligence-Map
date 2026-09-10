/**
 * URL du worker MapLibre servi depuis public/maplibre/
 * (copié depuis node_modules au postinstall / prebuild).
 *
 * Webpack ne peut pas résoudre `new URL(\`./${worker}\`, import.meta.url)`
 * dans le bundle maplibre-gl : le worker ne serait pas émis, et la carte
 * marine chercherait un .mjs à côté du chunk JS (404).
 */
export function maplibreWorkerUrl(publicUrl = process.env.PUBLIC_URL) {
  const base = String(publicUrl || "").replace(/\/$/, "");
  return `${base}/maplibre/maplibre-gl-worker.mjs`;
}
