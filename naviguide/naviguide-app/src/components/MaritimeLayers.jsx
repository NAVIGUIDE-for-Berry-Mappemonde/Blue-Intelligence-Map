/**
 * MaritimeLayers — 3 couches de données maritimes pour MapLibre GL JS
 *
 *  1. ZEE       — Zones Économiques Exclusives (VLIZ / Marine Regions, via WFS proxy)
 *  2. Ports WPI — World Port Index (NGA/MSI REST, via proxy)
 *  3. Balisage  — Balisage maritime SHOM (INSPIRE WFS proxy)
 *
 * Exports:
 *  - useMaritimeLayers()        → hook (state + data fetching)
 *  - MaritimeLayers(props)      → Source/Layer à placer DANS <Map>
 *  - MaritimeLayersPanel(props) → Panneau flottant de bascule (HORS <Map>)
 */

import { useEffect, useState } from "react";
import { Source, Layer } from "react-map-gl/maplibre";

const API_URL = import.meta.env.VITE_API_URL;
const EMPTY_FC = { type: "FeatureCollection", features: [] };

// ── Layer paint styles ────────────────────────────────────────────────────────

const ZEE_FILL_PAINT = {
  "fill-color": "rgba(14, 116, 144, 0.07)",
  "fill-outline-color": "rgba(14, 116, 144, 0)",
};
const ZEE_LINE_PAINT = {
  "line-color": "#0e7490",
  "line-width": 1.5,
  "line-dasharray": [5, 3],
  "line-opacity": 0.75,
};
const PORTS_CIRCLE_PAINT = {
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 2, 6, 4, 10, 7],
  "circle-color": "#f59e0b",
  "circle-stroke-width": 1,
  "circle-stroke-color": "#fff",
  "circle-opacity": 0.85,
};
const BALISAGE_CIRCLE_PAINT = {
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 4, 2, 10, 4, 14, 6],
  "circle-color": [
    "match",
    ["get", "couleur"],          // SHOM attribute for buoy colour
    "ROUGE",   "#ef4444",
    "VERT",    "#22c55e",
    "BLANC",   "#f8fafc",
    "JAUNE",   "#eab308",
    "#10b981", // default teal
  ],
  "circle-stroke-width": 0.8,
  "circle-stroke-color": "#fff",
  "circle-opacity": 0.9,
};

// ── Fetchers ──────────────────────────────────────────────────────────────────

async function fetchZee() {
  const res = await fetch(`${API_URL}/proxy/zee?maxFeatures=200`);
  if (!res.ok) throw new Error(`ZEE HTTP ${res.status}`);
  return res.json();
}

async function fetchPorts() {
  const res = await fetch(`${API_URL}/proxy/ports`);
  if (!res.ok) throw new Error(`Ports HTTP ${res.status}`);
  return res.json();
}

async function fetchBalisage() {
  const res = await fetch(`${API_URL}/proxy/balisage?count=800`);
  if (!res.ok) throw new Error(`Balisage HTTP ${res.status}`);
  return res.json();
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useMaritimeLayers
 * Gère l'état ON/OFF, les données GeoJSON et les états de chargement
 * pour les 3 couches maritimes.
 */
export function useMaritimeLayers() {
  const [showZee,      setShowZee]      = useState(false);
  const [showPorts,    setShowPorts]    = useState(false);
  const [showBalisage, setShowBalisage] = useState(false);

  const [zeeData,      setZeeData]      = useState(EMPTY_FC);
  const [portsData,    setPortsData]    = useState(EMPTY_FC);
  const [balisageData, setBalisageData] = useState(EMPTY_FC);

  const [loadingZee,      setLoadingZee]      = useState(false);
  const [loadingPorts,    setLoadingPorts]     = useState(false);
  const [loadingBalisage, setLoadingBalisage]  = useState(false);

  const [errorZee,      setErrorZee]      = useState(null);
  const [errorPorts,    setErrorPorts]    = useState(null);
  const [errorBalisage, setErrorBalisage] = useState(null);

  // Lazy load on first activation
  useEffect(() => {
    if (!showZee || zeeData.features.length > 0) return;
    setLoadingZee(true);
    setErrorZee(null);
    fetchZee()
      .then(setZeeData)
      .catch((e) => { console.warn("[MaritimeLayers] ZEE:", e); setErrorZee(e.message); })
      .finally(() => setLoadingZee(false));
  }, [showZee]);

  useEffect(() => {
    if (!showPorts || portsData.features.length > 0) return;
    setLoadingPorts(true);
    setErrorPorts(null);
    fetchPorts()
      .then(setPortsData)
      .catch((e) => { console.warn("[MaritimeLayers] Ports:", e); setErrorPorts(e.message); })
      .finally(() => setLoadingPorts(false));
  }, [showPorts]);

  useEffect(() => {
    if (!showBalisage || balisageData.features.length > 0) return;
    setLoadingBalisage(true);
    setErrorBalisage(null);
    fetchBalisage()
      .then(setBalisageData)
      .catch((e) => { console.warn("[MaritimeLayers] Balisage:", e); setErrorBalisage(e.message); })
      .finally(() => setLoadingBalisage(false));
  }, [showBalisage]);

  return {
    // Toggles
    showZee,      setShowZee,
    showPorts,    setShowPorts,
    showBalisage, setShowBalisage,
    // Data
    zeeData, portsData, balisageData,
    // Loading flags
    loadingZee, loadingPorts, loadingBalisage,
    // Error messages
    errorZee, errorPorts, errorBalisage,
  };
}

// ── Map layers (render inside <Map>) ─────────────────────────────────────────

/**
 * MaritimeLayers
 * Place les <Source> / <Layer> MapLibre GL JS dans l'arbre du composant <Map>.
 */
export function MaritimeLayers({
  showZee, zeeData,
  showPorts, portsData,
  showBalisage, balisageData,
}) {
  return (
    <>
      {/* ── ZEE polygons ──────────────────────────────────────────────────── */}
      <Source id="zee-source" type="geojson" data={showZee ? zeeData : EMPTY_FC}>
        <Layer id="zee-fill" type="fill" paint={ZEE_FILL_PAINT} />
        <Layer id="zee-line" type="line" paint={ZEE_LINE_PAINT} />
      </Source>

      {/* ── WPI ports ─────────────────────────────────────────────────────── */}
      <Source id="ports-source" type="geojson" data={showPorts ? portsData : EMPTY_FC}>
        <Layer id="ports-circle" type="circle" paint={PORTS_CIRCLE_PAINT} />
      </Source>

      {/* ── SHOM balisage ─────────────────────────────────────────────────── */}
      <Source id="balisage-source" type="geojson" data={showBalisage ? balisageData : EMPTY_FC}>
        <Layer id="balisage-circle" type="circle" paint={BALISAGE_CIRCLE_PAINT} />
      </Source>
    </>
  );
}

// ── Toggle panel (render outside <Map>) ──────────────────────────────────────

const LAYER_CONFIG = [
  {
    key: "zee",
    label: "ZEE",
    title: "Zones Économiques Exclusives (VLIZ)",
    color: "#0e7490",
    showKey: "showZee",
    toggleKey: "setShowZee",
    loadingKey: "loadingZee",
    errorKey: "errorZee",
  },
  {
    key: "ports",
    label: "Ports WPI",
    title: "Ports mondiaux — World Port Index (NGA)",
    color: "#f59e0b",
    showKey: "showPorts",
    toggleKey: "setShowPorts",
    loadingKey: "loadingPorts",
    errorKey: "errorPorts",
  },
  {
    key: "balisage",
    label: "Balisage",
    title: "Balisage maritime SHOM (France)",
    color: "#10b981",
    showKey: "showBalisage",
    toggleKey: "setShowBalisage",
    loadingKey: "loadingBalisage",
    errorKey: "errorBalisage",
  },
];

/**
 * MaritimeLayersPanel
 * Panneau flottant avec les boutons de bascule pour chaque couche maritime.
 * À placer EN DEHORS du composant <Map>, dans le div racine de l'application.
 */
export function MaritimeLayersPanel(props) {
  return (
    <div
      className="absolute bottom-6 left-4 z-20 flex flex-col gap-1.5"
      style={{ pointerEvents: "auto" }}
    >
      {/* Section label */}
      <div className="text-white/40 text-[10px] font-semibold uppercase tracking-widest px-1 mb-0.5 select-none">
        Couches
      </div>

      {LAYER_CONFIG.map(({ key, label, title, color, showKey, toggleKey, loadingKey, errorKey }) => {
        const active  = props[showKey];
        const loading = props[loadingKey];
        const error   = props[errorKey];

        return (
          <button
            key={key}
            onClick={() => props[toggleKey]((v) => !v)}
            title={title}
            className={[
              "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold",
              "shadow-lg transition-all duration-150 select-none",
              active
                ? "bg-slate-800/95 text-white border border-white/20"
                : "bg-slate-900/70 text-white/50 border border-white/10 hover:bg-slate-800/80 hover:text-white/80",
              error ? "border-red-500/50" : "",
            ].join(" ")}
          >
            {/* Status dot / spinner */}
            {loading ? (
              <div
                className="w-2.5 h-2.5 rounded-full border-2 border-white/30 border-t-white animate-spin flex-shrink-0"
              />
            ) : (
              <div
                className="w-2.5 h-2.5 rounded-full flex-shrink-0 transition-colors"
                style={{
                  backgroundColor: active ? color : "transparent",
                  border: `2px solid ${error ? "#ef4444" : color}`,
                }}
              />
            )}

            {/* Label */}
            <span>{label}</span>

            {/* Error badge */}
            {error && !loading && (
              <span className="ml-0.5 text-red-400" title={error}>⚠</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
