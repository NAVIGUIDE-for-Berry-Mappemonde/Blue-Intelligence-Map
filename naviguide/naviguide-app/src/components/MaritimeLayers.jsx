/**
 * MaritimeLayers — 3 couches de données maritimes pour MapLibre GL JS
 *
 *  1. ZEE         — Zones Économiques Exclusives (VLIZ / Marine Regions, via WFS proxy)
 *  2. Ports WPI   — World Port Index (NGA/MSI REST, via proxy, coords DMS→decimal)
 *  3. Balisage    — Balisage maritime via OpenSeaMap raster tiles (public, no auth)
 *                   NOTE: SHOM WFS remplacé car nécessite authentification (401).
 *
 * Exports:
 *  - useMaritimeLayers()        → hook (state + data fetching)
 *  - MaritimeLayers(props)      → Sources/Layers à placer DANS <Map>
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
  "line-opacity": 0.8,
};
const PORTS_CIRCLE_PAINT = {
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 2, 6, 4, 10, 7],
  "circle-color": "#f59e0b",
  "circle-stroke-width": 1,
  "circle-stroke-color": "#fff",
  "circle-opacity": 0.85,
};
// OpenSeaMap tiles — raster overlay, opacity controlled via show flag
const OPENSEAMAP_RASTER_PAINT = {
  "raster-opacity": 0.85,
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

  const [zeeData,   setZeeData]   = useState(EMPTY_FC);
  const [portsData, setPortsData] = useState(EMPTY_FC);

  const [loadingZee,   setLoadingZee]   = useState(false);
  const [loadingPorts, setLoadingPorts] = useState(false);

  const [errorZee,   setErrorZee]   = useState(null);
  const [errorPorts, setErrorPorts] = useState(null);

  // Lazy-load ZEE on first activation
  useEffect(() => {
    if (!showZee || zeeData.features.length > 0) return;
    setLoadingZee(true);
    setErrorZee(null);
    fetchZee()
      .then(setZeeData)
      .catch((e) => { console.warn("[MaritimeLayers] ZEE:", e); setErrorZee(e.message); })
      .finally(() => setLoadingZee(false));
  }, [showZee]);

  // Lazy-load WPI ports on first activation
  useEffect(() => {
    if (!showPorts || portsData.features.length > 0) return;
    setLoadingPorts(true);
    setErrorPorts(null);
    fetchPorts()
      .then(setPortsData)
      .catch((e) => { console.warn("[MaritimeLayers] Ports:", e); setErrorPorts(e.message); })
      .finally(() => setLoadingPorts(false));
  }, [showPorts]);

  return {
    // Toggles
    showZee,      setShowZee,
    showPorts,    setShowPorts,
    showBalisage, setShowBalisage,
    // Data
    zeeData,
    portsData,
    // Loading flags
    loadingZee,
    loadingPorts,
    loadingBalisage: false,   // OpenSeaMap tiles load automatically
    // Error messages
    errorZee,
    errorPorts,
    errorBalisage: null,
  };
}

// ── Map layers (render inside <Map>) ─────────────────────────────────────────

/**
 * MaritimeLayers
 * Place les Sources/Layers MapLibre GL JS dans l'arbre du composant <Map>.
 *
 *  - ZEE       : polygones GeoJSON via proxy backend
 *  - Ports WPI : points GeoJSON via proxy backend
 *  - Balisage  : tuiles raster OpenSeaMap (chargées directement depuis le navigateur)
 */
export function MaritimeLayers({
  showZee, zeeData,
  showPorts, portsData,
  showBalisage,
}) {
  return (
    <>
      {/* ── ZEE polygons ──────────────────────────────────────────────────── */}
      <Source id="zee-source" type="geojson" data={showZee ? zeeData : EMPTY_FC}>
        <Layer id="zee-fill" type="fill" paint={ZEE_FILL_PAINT} />
        <Layer id="zee-line" type="line" paint={ZEE_LINE_PAINT} />
      </Source>

      {/* ── WPI ports circles ─────────────────────────────────────────────── */}
      <Source id="ports-source" type="geojson" data={showPorts ? portsData : EMPTY_FC}>
        <Layer id="ports-circle" type="circle" paint={PORTS_CIRCLE_PAINT} />
      </Source>

      {/* ── OpenSeaMap balisage — raster tile overlay ─────────────────────── */}
      {showBalisage && (
        <Source
          id="openseamap-source"
          type="raster"
          tiles={["https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png"]}
          tileSize={256}
          attribution="© <a href='https://www.openseamap.org' target='_blank'>OpenSeaMap</a>"
        >
          <Layer
            id="openseamap-layer"
            type="raster"
            paint={OPENSEAMAP_RASTER_PAINT}
          />
        </Source>
      )}
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
    title: "Balisage maritime (OpenSeaMap)",
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
              <div className="w-2.5 h-2.5 rounded-full border-2 border-white/30 border-t-white animate-spin flex-shrink-0" />
            ) : (
              <div
                className="w-2.5 h-2.5 rounded-full flex-shrink-0 transition-colors"
                style={{
                  backgroundColor: active ? color : "transparent",
                  border: `2px solid ${error ? "#ef4444" : color}`,
                }}
              />
            )}
            <span>{label}</span>
            {error && !loading && (
              <span className="ml-0.5 text-red-400" title={error}>⚠</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
