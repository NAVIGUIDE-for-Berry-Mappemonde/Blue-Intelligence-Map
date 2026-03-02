/**
 * NAVIGUIDE v2 — Main Application
 *
 * Connects to the Multi-Agent Orchestrator (port 8002) to get the unified
 * Berry-Mappemonde expedition plan, then renders:
 *
 *  - Maritime route lines    coloured by anti-shipping score (green/yellow/orange)
 *  - Non-maritime dashed line (Halifax → Saint-Pierre SPM decoupled leg)
 *  - Territorial flag markers at each mandatory stopover
 *  - Piracy zone overlay markers (red dots)
 *  - Cyclone exposure overlay markers (purple dots)
 *  - Click popups on stopovers (risk breakdown) and risk zones (details)
 *  - Collapsible left sidebar (voyage stats + LLM briefing + alerts)
 */

import { useEffect, useRef, useState } from "react";
import Map, { Source, Layer, Marker, Popup } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { X, AlertTriangle, Shield, Anchor } from "lucide-react";

import { Sidebar } from "./components/Sidebar.jsx";
import { getFlagForWaypoint } from "./constants/waypoints.js";
import {
  antiShippingLineColor,
  riskBadgeClass,
  riskHex,
  antiShippingLabel,
  scoreToHex,
} from "./utils/riskColors.js";

const ORCHESTRATOR_URL = import.meta.env.VITE_ORCHESTRATOR_URL || "http://localhost:8002";

// ── Non-maritime segment (SPM decoupled leg — air travel) ─────────────────────
const NON_MARITIME_LEG = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [-63.0822, 18.0679],  // Marigot (Saint-Martin)
          [-63.5752, 44.6488],  // Halifax
          [-56.1778, 46.7811],  // Saint-Pierre-et-Miquelon
        ],
      },
    },
  ],
};

// ── Risk level colours ────────────────────────────────────────────────────────
function RiskBadge({ level }) {
  const cls = riskBadgeClass[level] || riskBadgeClass.UNKNOWN;
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      {level || "UNKNOWN"}
    </span>
  );
}

// ── Waypoint popup ────────────────────────────────────────────────────────────
function WaypointPopup({ stop, onClose }) {
  const p = stop.properties || {};
  const components = p.risk_components || {};
  const rows = [
    { label: "Weather",  value: components.weather_score },
    { label: "Piracy",   value: components.piracy_score },
    { label: "Medical",  value: components.medical_score },
    { label: "Cyclone",  value: components.cyclone_score },
  ];
  return (
    <div className="bg-white rounded-xl shadow-2xl overflow-hidden min-w-[240px] animate-fadeIn">
      <div className="bg-gradient-to-r from-blue-700 to-blue-800 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Anchor size={14} className="text-white/80" />
          <h4 className="text-white font-semibold text-sm">{p.name || "Stopover"}</h4>
        </div>
        <button
          onClick={onClose}
          className="text-white/70 hover:text-white w-6 h-6 flex items-center justify-center rounded hover:bg-white/20"
        >
          <X size={14} />
        </button>
      </div>
      <div className="p-4 space-y-3">
        {p.risk_level && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">Overall Risk</span>
            <div className="flex items-center gap-2">
              <RiskBadge level={p.risk_level} />
              <span className="text-xs text-slate-600">
                {p.risk_overall !== undefined ? p.risk_overall.toFixed(3) : ""}
              </span>
            </div>
          </div>
        )}
        {rows.some((r) => r.value !== undefined) && (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-slate-500 uppercase tracking-wide">
              Risk Breakdown
            </div>
            {rows.map(({ label, value }) =>
              value !== undefined ? (
                <div key={label} className="flex items-center justify-between gap-3">
                  <span className="text-xs text-slate-600 w-16">{label}</span>
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.min(value * 100, 100)}%`,
                        background: scoreToHex(1 - value),
                      }}
                    />
                  </div>
                  <span className="text-xs text-slate-500 w-8 text-right">
                    {(value * 100).toFixed(0)}%
                  </span>
                </div>
              ) : null
            )}
          </div>
        )}
        {!p.risk_level && (
          <div className="text-xs text-slate-400 text-center py-2">
            No risk data — intermediate waypoint
          </div>
        )}
      </div>
    </div>
  );
}

// ── Risk zone popup ───────────────────────────────────────────────────────────
function RiskZonePopup({ zone, onClose }) {
  const p = zone.properties || {};
  const isPiracy   = p.overlay_type === "piracy_zone";
  const headerBg   = isPiracy ? "from-red-700 to-red-800" : "from-purple-700 to-purple-800";
  const icon       = isPiracy ? "☠️" : "🌀";

  return (
    <div className="bg-white rounded-xl shadow-2xl overflow-hidden min-w-[220px] animate-fadeIn">
      <div className={`bg-gradient-to-r ${headerBg} px-4 py-3 flex items-center justify-between`}>
        <div className="flex items-center gap-2">
          <span>{icon}</span>
          <h4 className="text-white font-semibold text-sm">
            {isPiracy ? "Piracy Zone" : "Cyclone Exposure"}
          </h4>
        </div>
        <button
          onClick={onClose}
          className="text-white/70 hover:text-white w-6 h-6 flex items-center justify-center rounded hover:bg-white/20"
        >
          <X size={14} />
        </button>
      </div>
      <div className="p-4 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-500">Location</span>
          <span className="text-xs font-medium text-slate-700">{p.name || "—"}</span>
        </div>
        {p.zone && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">Zone</span>
            <span className="text-xs font-medium text-slate-700 text-right max-w-[140px]">{p.zone}</span>
          </div>
        )}
        {p.basin && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">Basin</span>
            <span className="text-xs font-medium text-slate-700 text-right max-w-[140px] leading-tight">{p.basin}</span>
          </div>
        )}
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-500">Risk Level</span>
          <RiskBadge level={p.risk_level} />
        </div>
        {p.score !== undefined && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">Score</span>
            <span className="text-xs font-semibold" style={{ color: scoreToHex(p.score) }}>
              {(p.score * 100).toFixed(0)}%
            </span>
          </div>
        )}
        {p.in_peak && (
          <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700 flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
            Peak season — passage strongly discouraged
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const mapRef = useRef(null);

  const [expeditionPlan, setExpeditionPlan]   = useState(null);
  const [loading, setLoading]                 = useState(true);
  const [loadingMsg, setLoadingMsg]           = useState("Connecting to NAVIGUIDE agents...");
  const [error, setError]                     = useState(null);
  const [sidebarOpen, setSidebarOpen]         = useState(true);
  const [selectedStop, setSelectedStop]       = useState(null);   // waypoint popup
  const [selectedZone, setSelectedZone]       = useState(null);   // risk zone popup

  // ── Fetch unified expedition plan from Orchestrator ───────────────────────
  useEffect(() => {
    const steps = [
      [600,  "Running Route Intelligence Agent..."],
      [2500, "Running Risk Assessment Agent..."],
      [5000, "Generating executive briefing..."],
    ];
    const timers = steps.map(([delay, msg]) =>
      setTimeout(() => setLoadingMsg(msg), delay)
    );

    fetch(`${ORCHESTRATOR_URL}/api/v1/expedition/plan/berry-mappemonde`, {
      method: "POST",
    })
      .then((r) => {
        if (!r.ok) throw new Error(`Orchestrator responded ${r.status}`);
        return r.json();
      })
      .then((data) => {
        timers.forEach(clearTimeout);
        setExpeditionPlan(data.expedition_plan || null);
        setLoading(false);
      })
      .catch((err) => {
        timers.forEach(clearTimeout);
        setError(err.message);
        setLoading(false);
      });

    return () => timers.forEach(clearTimeout);
  }, []);

  // ── Auto-fit map bounds once data loads ───────────────────────────────────
  useEffect(() => {
    if (!mapRef.current || !expeditionPlan) return;
    const features = expeditionPlan.unified_geojson?.features || [];
    const coords = features
      .filter((f) => f.geometry?.type === "LineString")
      .flatMap((f) => f.geometry.coordinates);
    if (coords.length === 0) return;

    const lons = coords.map((c) => c[0]);
    const lats = coords.map((c) => c[1]);
    mapRef.current.getMap().fitBounds(
      [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
      { padding: 80, duration: 1200 }
    );
  }, [expeditionPlan]);

  // ── Derive feature sets from unified_geojson ─────────────────────────────
  const allFeatures   = expeditionPlan?.unified_geojson?.features || [];

  const routeGeoJSON  = {
    type: "FeatureCollection",
    features: allFeatures.filter(
      (f) => f.geometry?.type === "LineString" && f.properties?.agent === "Agent1-RouteIntelligence"
    ),
  };

  const stopoverPoints = allFeatures.filter(
    (f) => f.geometry?.type === "Point" && f.properties?.type === "stopover"
  );

  const piracyPoints  = allFeatures.filter(
    (f) => f.properties?.overlay_type === "piracy_zone"
  );

  const cyclonePoints = allFeatures.filter(
    (f) => f.properties?.overlay_type === "cyclone_exposure"
  );

  // ── Loading screen ────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="h-screen w-screen bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900 flex flex-col items-center justify-center">
        <div className="flex flex-col items-center gap-6">
          <div className="relative">
            <div className="w-16 h-16 border-4 border-blue-500/20 border-t-blue-400 rounded-full animate-spin" />
            <div className="absolute inset-0 flex items-center justify-center text-blue-400 text-2xl">
              ⚓
            </div>
          </div>
          <div className="text-center">
            <div className="text-white font-bold text-xl tracking-widest mb-1">NAVIGUIDE</div>
            <div className="text-blue-300 text-sm font-medium">{loadingMsg}</div>
          </div>
          <div className="flex gap-1.5 mt-2">
            {["Route Intelligence", "Risk Assessment", "Briefing"].map((label, i) => (
              <div
                key={label}
                className="text-xs px-2.5 py-1 rounded-full border"
                style={{
                  borderColor: "rgba(59,130,246,0.4)",
                  color: "rgba(147,197,253,0.7)",
                  animationDelay: `${i * 0.3}s`,
                }}
              >
                {label}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ── Error screen ──────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="h-screen w-screen bg-slate-900 flex flex-col items-center justify-center gap-4">
        <AlertTriangle size={40} className="text-red-400" />
        <div className="text-white font-semibold text-lg">Orchestrator Unavailable</div>
        <div className="text-slate-400 text-sm text-center max-w-sm">
          Could not connect to the NAVIGUIDE orchestrator at{" "}
          <code className="text-blue-300">{ORCHESTRATOR_URL}</code>.
          <br />Make sure the backend services are running.
        </div>
        <div className="text-slate-600 text-xs mt-2 font-mono">{error}</div>
        <button
          onClick={() => window.location.reload()}
          className="mt-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  // ── Main map render ───────────────────────────────────────────────────────
  return (
    <div style={{ height: "100vh", width: "100vw", position: "relative" }}>

      {/* ── Sidebar ─────────────────────────────────────────────────────── */}
      <Sidebar
        plan={expeditionPlan}
        open={sidebarOpen}
        onToggle={() => setSidebarOpen((v) => !v)}
      />

      {/* ── Map ─────────────────────────────────────────────────────────── */}
      <Map
        ref={mapRef}
        initialViewState={{ latitude: 20, longitude: 0, zoom: 2 }}
        style={{ width: "100%", height: "100%" }}
        mapStyle="https://demotiles.maplibre.org/style.json"
        doubleClickZoom={false}
        dragRotate={false}
        touchZoomRotate={false}
        onLoad={(e) => {
          // Register directional arrow image for route animation
          const arrowSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>`;
          const img = new Image(24, 24);
          img.onload = () => { if (!e.target.hasImage("arrow")) e.target.addImage("arrow", img); };
          img.src = "data:image/svg+xml;base64," + btoa(arrowSvg);
        }}
      >

        {/* ── Maritime route lines (coloured by anti-shipping score) ──────── */}
        <Source id="routes" type="geojson" data={routeGeoJSON}>
          <Layer
            id="route-lines"
            type="line"
            paint={{
              "line-color": antiShippingLineColor,
              "line-width": 2.5,
              "line-opacity": 0.9,
            }}
          />
          <Layer
            id="route-arrows"
            type="symbol"
            layout={{
              "symbol-placement": "line",
              "symbol-spacing": 120,
              "icon-image": "arrow",
              "icon-size": 0.85,
              "icon-rotation-alignment": "map",
              "icon-allow-overlap": true,
              "icon-ignore-placement": true,
            }}
          />
        </Source>

        {/* ── Non-maritime SPM leg (dashed orange) ────────────────────────── */}
        <Source id="non-maritime" type="geojson" data={NON_MARITIME_LEG}>
          <Layer
            id="non-maritime-line"
            type="line"
            paint={{
              "line-color": "#f97316",
              "line-width": 3,
              "line-dasharray": [2, 2],
              "line-opacity": 0.75,
            }}
          />
        </Source>

        {/* ── Stopover flag markers ────────────────────────────────────────── */}
        {stopoverPoints.map((stop, i) => {
          const [lon, lat] = stop.geometry.coordinates;
          const name       = stop.properties?.name || "";
          const flag       = getFlagForWaypoint(name);
          if (!flag) return null;
          return (
            <Marker key={`stop-${i}`} longitude={lon} latitude={lat} anchor="bottom">
              <img
                src={flag}
                alt={name}
                title={name}
                onClick={() => setSelectedStop(stop)}
                style={{
                  width: 32,
                  height: 24,
                  borderRadius: 4,
                  boxShadow: "0 1px 4px rgba(0,0,0,0.4)",
                  cursor: "pointer",
                  outline: stop.properties?.risk_level === "CRITICAL" ? "2px solid #ef4444" :
                           stop.properties?.risk_level === "HIGH"     ? "2px solid #f97316" : "none",
                  outlineOffset: 2,
                }}
              />
            </Marker>
          );
        })}

        {/* ── Stopover popup ───────────────────────────────────────────────── */}
        {selectedStop && (
          <Popup
            longitude={selectedStop.geometry.coordinates[0]}
            latitude={selectedStop.geometry.coordinates[1]}
            closeButton={false}
            closeOnClick={false}
            anchor="top"
            offset={30}
            onClose={() => setSelectedStop(null)}
            className="!bg-transparent !border-none !shadow-none"
          >
            <WaypointPopup stop={selectedStop} onClose={() => setSelectedStop(null)} />
          </Popup>
        )}

        {/* ── Piracy zone markers (red) ────────────────────────────────────── */}
        {piracyPoints.map((zone, i) => {
          const [lon, lat] = zone.geometry.coordinates;
          return (
            <Marker key={`piracy-${i}`} longitude={lon} latitude={lat}>
              <div
                onClick={() => setSelectedZone(zone)}
                title={`Piracy: ${zone.properties?.zone || zone.properties?.name}`}
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: "50%",
                  background: riskHex[zone.properties?.risk_level] || "#ef4444",
                  border: "2px solid white",
                  boxShadow: "0 0 8px rgba(239,68,68,0.6)",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 10,
                }}
              >
                ☠
              </div>
            </Marker>
          );
        })}

        {/* ── Cyclone exposure markers (purple) ───────────────────────────── */}
        {cyclonePoints.map((zone, i) => {
          const [lon, lat] = zone.geometry.coordinates;
          return (
            <Marker key={`cyclone-${i}`} longitude={lon} latitude={lat}>
              <div
                onClick={() => setSelectedZone(zone)}
                title={`Cyclone: ${zone.properties?.basin}`}
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: "50%",
                  background: "#a855f7",
                  border: "2px solid white",
                  boxShadow: "0 0 8px rgba(168,85,247,0.6)",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 10,
                }}
              >
                🌀
              </div>
            </Marker>
          );
        })}

        {/* ── Risk zone popup ──────────────────────────────────────────────── */}
        {selectedZone && (
          <Popup
            longitude={selectedZone.geometry.coordinates[0]}
            latitude={selectedZone.geometry.coordinates[1]}
            closeButton={false}
            closeOnClick={false}
            anchor="top"
            offset={25}
            onClose={() => setSelectedZone(null)}
            className="!bg-transparent !border-none !shadow-none"
          >
            <RiskZonePopup zone={selectedZone} onClose={() => setSelectedZone(null)} />
          </Popup>
        )}

      </Map>

      {/* ── Top-right info badge ─────────────────────────────────────────── */}
      {expeditionPlan && (
        <div className="absolute top-4 right-4 z-10 bg-slate-900/90 border border-slate-700 rounded-xl px-3 py-2 text-xs text-slate-300 shadow-lg space-y-1 backdrop-blur-sm">
          <div className="font-semibold text-white text-sm">Berry-Mappemonde</div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Risk:</span>
            <span
              style={{
                color: riskHex[expeditionPlan.voyage_statistics?.expedition_risk_level] || "#94a3b8",
              }}
              className="font-semibold"
            >
              {expeditionPlan.voyage_statistics?.expedition_risk_level || "—"}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Distance:</span>
            <span className="font-medium">
              {expeditionPlan.voyage_statistics?.total_distance_nm
                ? `${expeditionPlan.voyage_statistics.total_distance_nm.toLocaleString()} nm`
                : "—"}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
