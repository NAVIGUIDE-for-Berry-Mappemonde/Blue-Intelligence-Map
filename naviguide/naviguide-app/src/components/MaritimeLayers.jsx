/**
 * MaritimeLayers — couches de données maritimes pour MapLibre GL JS
 *
 *  1. ZEE         — Zones Économiques Exclusives (VLIZ / Marine Regions, via WFS proxy)
 *  2. Ports WPI   — World Port Index (NGA/MSI REST, via proxy, coords DMS→decimal)
 *  3. Balisage    — Balisage maritime via OpenSeaMap raster tiles (public, no auth)
 *                   NOTE: SHOM WFS remplacé car nécessite authentification (401).
 *  4. Blue Intelligence — les 5 modes de blueintelligence.online en points GeoJSON
 *     (Projets, Marinas, Capitaineries, Ports d'Entrée, AMP), chargés à la demande
 *     via le proxy même-origine « /bi » → API Blue Intelligence /api/export/*.
 *
 * Exports:
 *  - useMaritimeLayers()        → hook (state + data fetching)
 *  - MaritimeLayers(props)      → Sources/Layers à placer DANS <Map>
 *  - MaritimeLayersPanel(props) → Panneau flottant de bascule (HORS <Map>)
 *  - BI_LAYER_CONFIG            → config des toggles Blue Intelligence (Sidebar)
 */

import { useEffect, useState } from "react";
import { Source, Layer } from "react-map-gl/maplibre";
import { useLang } from "../i18n/LangContext.jsx";

// Toujours URL absolue pour les tuiles (évite les problèmes de proxy Vite / preview).
const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
// Exports Blue Intelligence — même-origine par défaut : vite proxy en dev,
// nginx (VPS) ou proxy_server.py (complete.dev) en production.
const BI_BASE = import.meta.env.VITE_BI_API_URL || "/bi";
const EMPTY_FC = { type: "FeatureCollection", features: [] };

// ── Layer paint styles ────────────────────────────────────────────────────────

// ZEE via WMS — layer eez_boundaries = limites uniquement (polylignes, pas de polygones)
// Tuiles 512×512 pour un rendu plus fin au zoom minimal (moins de flou/épaisseur)
const ZEE_WMS_TILES = [
  `${API_BASE}/proxy/zee/wms?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=eez_boundaries&FORMAT=image/png&TRANSPARENT=true&SRS=EPSG:3857&WIDTH=512&HEIGHT=512&BBOX={bbox-epsg-3857}`,
];
const PORTS_CIRCLE_PAINT = {
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 2, 6, 4, 10, 7],
  "circle-color": "#f59e0b",
  "circle-stroke-width": 1,
  "circle-stroke-color": "#fff",
  "circle-opacity": 0.85,
};

// Couleurs des modes Blue Intelligence (cf. README Blue Intelligence)
export const BI_COLORS = {
  biProjects:      "#06b6d4", // cyan  — Projets de conservation marine
  biMarinas:       "#ef4444", // rouge — Marinas OSM
  biCapitaineries: "#7dd3fc", // ciel  — Capitaineries
  biPoe:           "#d97706", // ambre — Ports d'Entrée (formalités)
  biAmp:           "#22c55e", // vert  — Aires Marines Protégées (centroïdes)
};

// Couches denses (marinas ≈ dizaines de milliers de points) → cercles plus fins
const biCirclePaint = (color) => ({
  "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 1.5, 6, 3.5, 10, 6.5],
  "circle-color": color,
  "circle-stroke-width": 1,
  "circle-stroke-color": "#fff",
  "circle-opacity": 0.85,
});
// OpenSeaMap tiles — raster overlay, opacity controlled via show flag
const OPENSEAMAP_RASTER_PAINT = {
  "raster-opacity": 0.85,
};

// ── Fetchers ──────────────────────────────────────────────────────────────────

async function fetchPorts() {
  const url = `${API_BASE}/proxy/ports`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Ports HTTP ${res.status}`);
  return res.json();
}

// ── Hook ──────────────────────────────────────────────────────────────────────

/**
 * useBiLayer — une couche Blue Intelligence : OFF par défaut,
 * fetch au premier passage à ON (les exports peuvent être volumineux).
 */
function useBiLayer(path) {
  const [show, setShow] = useState(false);
  const [data, setData] = useState(EMPTY_FC);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!show || data.features.length > 0) return;
    setLoading(true);
    setError(null);
    fetch(`${BI_BASE}${path}`)
      .then((res) => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
      .then((fc) => setData(fc?.type === "FeatureCollection" ? fc : EMPTY_FC))
      .catch((e) => {
        console.warn("[MaritimeLayers] Blue Intelligence", path, e.message || e);
        setError(e.message || String(e));
      })
      .finally(() => setLoading(false));
  }, [show]);

  return { show, setShow, data, loading, error };
}

/**
 * useMaritimeLayers
 * Gère l'état ON/OFF, les données GeoJSON et les états de chargement
 * pour les couches maritimes et les couches Blue Intelligence.
 */
/**
 * AMP en polygones via GET /amp?bbox= (pas l'export centroïdes).
 */
function useAmpPolygons(mapRef) {
  const [show, setShow] = useState(false);
  const [data, setData] = useState(EMPTY_FC);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!show) return undefined;
    let cancelled = false;
    let timer = null;

    const load = () => {
      const map = mapRef?.current?.getMap?.();
      if (!map) return;
      const b = map.getBounds();
      const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(",");
      setLoading(true);
      setError(null);
      fetch(`${BI_BASE}/amp?bbox=${encodeURIComponent(bbox)}`)
        .then((res) => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
        .then((fc) => {
          if (!cancelled) setData(fc?.type === "FeatureCollection" ? fc : EMPTY_FC);
        })
        .catch((e) => {
          if (!cancelled) {
            console.warn("[MaritimeLayers] AMP", e.message || e);
            setError(e.message || String(e));
          }
        })
        .finally(() => { if (!cancelled) setLoading(false); });
    };

    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(load, 420);
    };

    const attach = () => {
      const map = mapRef?.current?.getMap?.();
      if (!map) return false;
      map.on("moveend", schedule);
      map.on("zoomend", schedule);
      load();
      return true;
    };

    if (!attach()) {
      const poll = setInterval(() => { if (attach()) clearInterval(poll); }, 250);
      return () => {
        cancelled = true;
        clearInterval(poll);
        clearTimeout(timer);
      };
    }

    return () => {
      cancelled = true;
      clearTimeout(timer);
      const map = mapRef?.current?.getMap?.();
      if (map) {
        map.off("moveend", schedule);
        map.off("zoomend", schedule);
      }
    };
  }, [show, mapRef]);

  return { show, setShow, data, loading, error };
}

export function useMaritimeLayers(mapRef) {
  // Couches actives par défaut — chargement différé pour ne pas bloquer le rendu initial
  const [showZee,      setShowZee]      = useState(true);
  const [showPorts,    setShowPorts]    = useState(true);
  const [showBalisage, setShowBalisage] = useState(true);

  const [portsData, setPortsData] = useState(EMPTY_FC);

  const [loadingPorts, setLoadingPorts] = useState(false);

  const [errorPorts, setErrorPorts] = useState(null);

  // Chargement Ports — immédiat
  useEffect(() => {
    if (!showPorts || portsData.features.length > 0) return;
    setLoadingPorts(true);
    setErrorPorts(null);
    fetchPorts()
      .then((data) => { setPortsData(data); })
      .catch((e) => { console.warn("[MaritimeLayers] Ports:", e.message || e); setErrorPorts(e.message || String(e)); })
      .finally(() => setLoadingPorts(false));
  }, [showPorts]);

  // Couches Blue Intelligence — les 5 modes de blueintelligence.online
  const biProjects      = useBiLayer("/export/geojson");
  const biMarinas       = useBiLayer("/export/marinas.geojson");
  const biCapitaineries = useBiLayer("/export/capitaineries.geojson");
  const biPoe           = useBiLayer("/export/poe.geojson");
  const biAmp           = useAmpPolygons(mapRef);

  return {
    // Toggles
    showZee,      setShowZee,
    showPorts,    setShowPorts,
    showBalisage, setShowBalisage,
    // Data
    portsData,
    // Loading flags
    loadingZee: false,   // ZEE WMS = tuiles, pas de fetch
    loadingPorts,
    loadingBalisage: false,
    // Error messages
    errorZee: null,
    errorPorts,
    errorBalisage: null,
    // Blue Intelligence — Projets
    showBiProjects: biProjects.show,           setShowBiProjects: biProjects.setShow,
    biProjectsData: biProjects.data,
    loadingBiProjects: biProjects.loading,     errorBiProjects: biProjects.error,
    // Blue Intelligence — Marinas
    showBiMarinas: biMarinas.show,             setShowBiMarinas: biMarinas.setShow,
    biMarinasData: biMarinas.data,
    loadingBiMarinas: biMarinas.loading,       errorBiMarinas: biMarinas.error,
    // Blue Intelligence — Capitaineries
    showBiCapitaineries: biCapitaineries.show, setShowBiCapitaineries: biCapitaineries.setShow,
    biCapitaineriesData: biCapitaineries.data,
    loadingBiCapitaineries: biCapitaineries.loading, errorBiCapitaineries: biCapitaineries.error,
    // Blue Intelligence — Ports d'Entrée (formalités)
    showBiPoe: biPoe.show,                     setShowBiPoe: biPoe.setShow,
    biPoeData: biPoe.data,
    loadingBiPoe: biPoe.loading,               errorBiPoe: biPoe.error,
    // Blue Intelligence — AMP
    showBiAmp: biAmp.show,                     setShowBiAmp: biAmp.setShow,
    biAmpData: biAmp.data,
    loadingBiAmp: biAmp.loading,               errorBiAmp: biAmp.error,
  };
}

// ── Map layers (render inside <Map>) ─────────────────────────────────────────

/**
 * MaritimeLayers
 * Place les Sources/Layers MapLibre GL JS dans l'arbre du composant <Map>.
 *
 * IMPORTANT: toutes les sources sont TOUJOURS montées (pas de rendu conditionnel).
 * La visibilité est contrôlée via layout.visibility pour éviter les erreurs
 * MapLibre au mount/unmount des sources ("Source already exists", race conditions).
 *
 *  - ZEE       : polygones GeoJSON via proxy backend
 *  - Ports WPI : points GeoJSON via proxy backend
 *  - Balisage  : tuiles raster OpenSeaMap (chargées directement depuis le navigateur)
 */
export function MaritimeLayers({
  showZee,
  showPorts, portsData,
  showBiProjects,      biProjectsData,
  showBiMarinas,       biMarinasData,
  showBiCapitaineries, biCapitaineriesData,
  showBiPoe,           biPoeData,
  showBiAmp,           biAmpData,
}) {
  const vis = (flag) => ({ visibility: flag ? "visible" : "none" });

  return (
    <>
      {/* ── ZEE via WMS (tuiles à la demande, instantané) ────────────────── */}
      <Source
        id="zee-source"
        type="raster"
        tiles={ZEE_WMS_TILES}
        tileSize={512}
        minzoom={1}
        maxzoom={18}
      >
        <Layer
          id="zee-layer"
          type="raster"
          layout={vis(showZee)}
          paint={{
            "raster-opacity": ["interpolate", ["linear"], ["zoom"], 1, 0.25, 3, 0.45, 6, 0.7, 10, 0.9],
            "raster-fade-duration": 0,
            "raster-resampling": "nearest",
          }}
        />
      </Source>

      {/* ── WPI ports circles ───────────────────────────────────────────── */}
      <Source id="ports-source" type="geojson" data={portsData}>
        <Layer id="ports-circle" type="circle" layout={vis(showPorts)} paint={PORTS_CIRCLE_PAINT} />
      </Source>

      {/* ── Blue Intelligence — 5 modes en points (couleurs du site BI) ──── */}
      <Source id="bi-amp-source" type="geojson" data={biAmpData ?? EMPTY_FC}>
        <Layer
          id="bi-amp-fill"
          type="fill"
          layout={vis(showBiAmp)}
          filter={["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false]}
          paint={{ "fill-color": BI_COLORS.biAmp, "fill-opacity": 0.28 }}
        />
        <Layer
          id="bi-amp-line"
          type="line"
          layout={vis(showBiAmp)}
          filter={["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false]}
          paint={{ "line-color": "#15803d", "line-width": 1.2 }}
        />
        <Layer
          id="bi-amp-circle"
          type="circle"
          layout={vis(showBiAmp)}
          filter={["==", ["geometry-type"], "Point"]}
          paint={biCirclePaint(BI_COLORS.biAmp)}
        />
      </Source>
      <Source id="bi-projects-source" type="geojson" data={biProjectsData ?? EMPTY_FC}>
        <Layer id="bi-projects-circle" type="circle" layout={vis(showBiProjects)} paint={biCirclePaint(BI_COLORS.biProjects)} />
      </Source>
      <Source id="bi-marinas-source" type="geojson" data={biMarinasData ?? EMPTY_FC}>
        <Layer id="bi-marinas-circle" type="circle" layout={vis(showBiMarinas)} paint={biCirclePaint(BI_COLORS.biMarinas)} />
      </Source>
      <Source id="bi-capitaineries-source" type="geojson" data={biCapitaineriesData ?? EMPTY_FC}>
        <Layer id="bi-capitaineries-circle" type="circle" layout={vis(showBiCapitaineries)} paint={biCirclePaint(BI_COLORS.biCapitaineries)} />
      </Source>
      <Source id="bi-poe-source" type="geojson" data={biPoeData ?? EMPTY_FC}>
        <Layer id="bi-poe-circle" type="circle" layout={vis(showBiPoe)} paint={biCirclePaint(BI_COLORS.biPoe)} />
      </Source>
    </>
  );
}

/** Balisage — raster au-dessus de tout (routes, markers). À placer EN DERNIER dans <Map>. */
const SEAMARK_TILES = [
  `${API_BASE}/proxy/seamark/{z}/{x}/{y}.png`,
  "https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
];

export function BalisageLayer({ show }) {
  return (
    <Source
      id="openseamap-source"
      type="raster"
      tiles={SEAMARK_TILES}
      tileSize={256}
      minzoom={1}
      maxzoom={19}
      attribution="© OpenSeaMap"
    >
      <Layer
        id="openseamap-layer"
        type="raster"
        layout={{ visibility: show ? "visible" : "none" }}
        paint={{
          "raster-opacity": 1,
          "raster-fade-duration": 0,
        }}
      />
    </Source>
  );
}

// ── Toggle panel (render outside <Map>) ──────────────────────────────────────

const LAYER_CONFIG = [
  { key: "zee",      labelKey: "layerZee",      titleKey: "layerZeeTitle",      color: "#0e7490", showKey: "showZee",      toggleKey: "setShowZee",      loadingKey: "loadingZee",      errorKey: "errorZee" },
  { key: "ports",    labelKey: "layerPorts",    titleKey: "layerPortsTitle",    color: "#f59e0b", showKey: "showPorts",    toggleKey: "setShowPorts",    loadingKey: "loadingPorts",    errorKey: "errorPorts" },
  { key: "balisage", labelKey: "layerBalisage", titleKey: "layerBalisageTitle", color: "#10b981", showKey: "showBalisage", toggleKey: "setShowBalisage", loadingKey: "loadingBalisage", errorKey: "errorBalisage" },
];

/** Toutes les couches carte — une seule grille de pastilles dans la Sidebar. */
export const ALL_LAYER_CONFIG = [
  ...LAYER_CONFIG,
  { key: "biProjects",      labelKey: "layerBiProjects",      titleKey: "layerBiProjectsTitle",      color: BI_COLORS.biProjects,      showKey: "showBiProjects",      toggleKey: "setShowBiProjects",      loadingKey: "loadingBiProjects",      errorKey: "errorBiProjects" },
  { key: "biMarinas",       labelKey: "layerBiMarinas",       titleKey: "layerBiMarinasTitle",       color: BI_COLORS.biMarinas,       showKey: "showBiMarinas",       toggleKey: "setShowBiMarinas",       loadingKey: "loadingBiMarinas",       errorKey: "errorBiMarinas" },
  { key: "biCapitaineries", labelKey: "layerBiCapitaineries", titleKey: "layerBiCapitaineriesTitle", color: BI_COLORS.biCapitaineries, showKey: "showBiCapitaineries", toggleKey: "setShowBiCapitaineries", loadingKey: "loadingBiCapitaineries", errorKey: "errorBiCapitaineries" },
  { key: "biPoe",           labelKey: "layerBiPoe",           titleKey: "layerBiPoeTitle",           color: BI_COLORS.biPoe,           showKey: "showBiPoe",           toggleKey: "setShowBiPoe",           loadingKey: "loadingBiPoe",           errorKey: "errorBiPoe" },
  { key: "biAmp",           labelKey: "layerBiAmp",           titleKey: "layerBiAmpTitle",           color: BI_COLORS.biAmp,           showKey: "showBiAmp",           toggleKey: "setShowBiAmp",           loadingKey: "loadingBiAmp",           errorKey: "errorBiAmp" },
];

/** @deprecated — utiliser ALL_LAYER_CONFIG */
export const BI_LAYER_CONFIG = [
  { key: "biProjects",      labelKey: "layerBiProjects",      titleKey: "layerBiProjectsTitle",      color: BI_COLORS.biProjects,      showKey: "showBiProjects",      toggleKey: "setShowBiProjects",      loadingKey: "loadingBiProjects",      errorKey: "errorBiProjects" },
  { key: "biMarinas",       labelKey: "layerBiMarinas",       titleKey: "layerBiMarinasTitle",       color: BI_COLORS.biMarinas,       showKey: "showBiMarinas",       toggleKey: "setShowBiMarinas",       loadingKey: "loadingBiMarinas",       errorKey: "errorBiMarinas" },
  { key: "biCapitaineries", labelKey: "layerBiCapitaineries", titleKey: "layerBiCapitaineriesTitle", color: BI_COLORS.biCapitaineries, showKey: "showBiCapitaineries", toggleKey: "setShowBiCapitaineries", loadingKey: "loadingBiCapitaineries", errorKey: "errorBiCapitaineries" },
  { key: "biPoe",           labelKey: "layerBiPoe",           titleKey: "layerBiPoeTitle",           color: BI_COLORS.biPoe,           showKey: "showBiPoe",           toggleKey: "setShowBiPoe",           loadingKey: "loadingBiPoe",           errorKey: "errorBiPoe" },
  { key: "biAmp",           labelKey: "layerBiAmp",           titleKey: "layerBiAmpTitle",           color: BI_COLORS.biAmp,           showKey: "showBiAmp",           toggleKey: "setShowBiAmp",           loadingKey: "loadingBiAmp",           errorKey: "errorBiAmp" },
];

/**
 * MaritimeLayersPanel
 * Panneau flottant avec les boutons de bascule pour chaque couche maritime.
 * À placer EN DEHORS du composant <Map>, dans le div racine de l'application.
 */
export function MaritimeLayersPanel(props) {
  const { t } = useLang();
  return (
    /* Centré en bas, entre les deux sidebars (chacune 320px) — toujours visible */
    <div
      className="absolute bottom-5 left-1/2 -translate-x-1/2 z-25 flex flex-row items-center gap-1.5
                 bg-slate-900/80 backdrop-blur-sm border border-white/10 rounded-full px-3 py-1.5 shadow-xl"
      style={{ pointerEvents: "auto", zIndex: 25 }}
    >
      {/* Label */}
      <span className="text-white/35 text-[9px] font-semibold uppercase tracking-widest mr-1 select-none">
        {t("layersLabel")}
      </span>

      {LAYER_CONFIG.map(({ key, labelKey, titleKey, color, showKey, toggleKey, loadingKey, errorKey }) => {
        const active  = props[showKey];
        const loading = props[loadingKey];
        const error   = props[errorKey];

        return (
          <button
            key={key}
            onClick={() => props[toggleKey]((v) => !v)}
            title={t(titleKey)}
            className={[
              "flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold",
              "transition-all duration-150 select-none",
              active
                ? "bg-slate-700/90 text-white border border-white/20"
                : "bg-transparent text-white/45 border border-white/10 hover:text-white/80 hover:bg-slate-700/50",
              error ? "border-red-500/50" : "",
            ].join(" ")}
          >
            {loading ? (
              <div className="w-2 h-2 rounded-full border-2 border-white/30 border-t-white animate-spin flex-shrink-0" />
            ) : (
              <div
                className="w-2 h-2 rounded-full flex-shrink-0 transition-colors"
                style={{
                  backgroundColor: active ? color : "transparent",
                  border: `1.5px solid ${error ? "#ef4444" : color}`,
                }}
              />
            )}
            <span>{t(labelKey)}</span>
            {error && !loading && (
              <span className="text-red-400 text-[10px]" title={error}>⚠</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
