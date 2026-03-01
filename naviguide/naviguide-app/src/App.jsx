import { useCallback, useEffect, useRef, useState } from "react";
import Map, { Source, Layer, Marker, Popup } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { ITINERARY_POINTS } from "./constants/itineraryPoints";
import { X, Undo2, Redo2 } from "lucide-react";
import { WindDirectionArrow } from "./components/map/WindDirectionArrow";
import { getCardinalDirection } from "./utils/getCardinalDirection";
import { Sidebar } from "./components/Sidebar";
import { ExportSidebar } from "./components/ExportSidebar";
import { useLang } from "./i18n/LangContext.jsx";
import {
  useMaritimeLayers,
  MaritimeLayers,
  MaritimeLayersPanel,
} from "./components/MaritimeLayers";
import { useMarkerOffsets } from "./hooks/useMarkerOffsets";
import { CatamaranMarker } from "./components/CatamaranMarker";
import { useLegContext } from "./hooks/useLegContext";

const API_URL = import.meta.env.VITE_API_URL;
const ORCHESTRATOR_URL = import.meta.env.VITE_ORCHESTRATOR_URL;

// La Rochelle — position de départ du catamaran en mode simulation
const LA_ROCHELLE_POS = { lat: 46.1541, lon: -1.167 };

// ── Orchestrator plan cache (localStorage, 24 h TTL, per language) ───────────
const PLAN_CACHE_TTL = 24 * 60 * 60 * 1000; // 24 hours

function planCacheKey(lang) { return `naviguide_expedition_plan_v1_${lang}`; }

function getCachedPlan(lang) {
  try {
    const raw = localStorage.getItem(planCacheKey(lang));
    if (!raw) return null;
    const { data, ts } = JSON.parse(raw);
    if (Date.now() - ts > PLAN_CACHE_TTL) { localStorage.removeItem(planCacheKey(lang)); return null; }
    return data;
  } catch { return null; }
}

function setCachedPlan(lang, data) {
  try { localStorage.setItem(planCacheKey(lang), JSON.stringify({ data, ts: Date.now() })); } catch {}
}

const SEGMENT_BATCH_SIZE = 4; // legs fetched in parallel per batch

export default function App() {
  const { lang, t } = useLang();
  const mapRef = useRef(null);
  const [segments, setSegments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // ── Export sidebar ────────────────────────────────────────────────────────────
  const [showExport, setShowExport] = useState(false);

  // ── Map viewport ──────────────────────────────────────────────────────────────
  const [viewport, setViewport] = useState({
    longitude: 0,
    latitude: 20,
    zoom: 2,
  });

  // ── Maritime layers toggle ────────────────────────────────────────────────────
  const maritimeLayers = useMaritimeLayers();

  // ── Marker offsets (dynamic, collision-aware) ─────────────────────────────────
  const markerOffsets = useMarkerOffsets(ITINERARY_POINTS, viewport.zoom);

  // ── Popup state ───────────────────────────────────────────────────────────────
  const [selectedPoint, setSelectedPoint] = useState(null);
  const [hoveredPoint,  setHoveredPoint]  = useState(null);

  // ── Expedition plan (orchestrator) ────────────────────────────────────────────
  const [expeditionPlan,        setExpeditionPlan]        = useState(null);
  const [expeditionPlanLoading, setExpeditionPlanLoading] = useState(false);
  const [expeditionPlanError,   setExpeditionPlanError]   = useState(null);

  // ── Undo / Redo history ───────────────────────────────────────────────────────
  const [history,      setHistory]      = useState([[]]);
  const [historyIndex, setHistoryIndex] = useState(0);

  // ── Waypoint drawing mode ─────────────────────────────────────────────────────
  const [drawingMode,    setDrawingMode]    = useState(false);
  const [drawnWaypoints, setDrawnWaypoints] = useState([]);

  // ── Active drawn-waypoint popup ───────────────────────────────────────────────
  const [activeDrawnWpt, setActiveDrawnWpt] = useState(null); // index | null

  // ── Wind widget ───────────────────────────────────────────────────────────────
  const [windData, setWindData] = useState(null);

  // ── Simulation mode — catamaran draggable ────────────────────────────────────
  const [simulationMode, setSimulationMode] = useState(false);
  const [catamaranPos,   setCatamaranPos]   = useState(null);  // { lat, lon }
  // Index courant dans ITINERARY_POINTS (La Rochelle = 1, le départ maritime)
  const [simPointIndex,  setSimPointIndex]  = useState(1);

  // Position par défaut : La Rochelle (point de départ maritime de l'expédition)
  const initialCatamaranPos = LA_ROCHELLE_POS;
  const activeCatamaranPos  = catamaranPos ?? initialCatamaranPos;

  // Avance le catamaran au milieu du prochain segment (escale ou point intermédiaire)
  const advanceCatamaranToNextMidpoint = useCallback(() => {
    if (simPointIndex >= ITINERARY_POINTS.length - 1) return;
    const from = ITINERARY_POINTS[simPointIndex];
    const to   = ITINERARY_POINTS[simPointIndex + 1];
    setCatamaranPos({ lat: (from.lat + to.lat) / 2, lon: (from.lon + to.lon) / 2 });
    setSimPointIndex(idx => idx + 1);
  }, [simPointIndex]);

  // Leg context : snap géométrique + métriques
  const legContext = useLegContext(
    simulationMode ? activeCatamaranPos : null,
    segments
  );

  // ── Route fetch ───────────────────────────────────────────────────────────────
  useEffect(() => {
    setLoading(true);
    setError(null);

    const points = ITINERARY_POINTS.map((p) => [p.lon, p.lat]);

    fetch(`${API_URL}/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ waypoints: points }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setSegments(data.segments || []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // ── Expedition plan fetch (orchestrator) ─────────────────────────────────────
  useEffect(() => {
    const cached = getCachedPlan(lang);
    if (cached) { setExpeditionPlan(cached); return; }

    setExpeditionPlanLoading(true);
    setExpeditionPlanError(null);

    fetch(`${ORCHESTRATOR_URL}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language: lang,
        waypoints: ITINERARY_POINTS.map(p => ({
          name: p.name,
          lat:  p.lat,
          lon:  p.lon,
          type: p.flag ? "escale_obligatoire" : "point_intermediaire",
        })),
      }),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`Orchestrator HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setExpeditionPlan(data);
        setCachedPlan(lang, data);
      })
      .catch((e) => setExpeditionPlanError(e.message))
      .finally(() => setExpeditionPlanLoading(false));
  }, [lang]);

  // ── Wind data fetch ───────────────────────────────────────────────────────────
  useEffect(() => {
    fetch(`${API_URL}/wind?lat=46.15&lon=-1.17`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => data && setWindData(data))
      .catch(() => {});
  }, []);

  // ── GeoJSON layers ────────────────────────────────────────────────────────────
  const routeGeoJSON = {
    type: "FeatureCollection",
    features: segments.map((seg) => ({
      type: "Feature",
      geometry: { type: "LineString", coordinates: seg.coords || [] },
      properties: { mode: seg.mode },
    })),
  };

  // Drawn waypoints with metadata as Point features (only if name or flags set)
  const drawnWaypointsGeoJSON = {
    type: "FeatureCollection",
    features: drawnWaypoints
      .filter(wp => wp.name || wp.flag)
      .map((wp, i) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [wp.lon, wp.lat] },
        properties: { index: i, name: wp.name || "", flag: !!wp.flag },
      })),
  };

  // ── Layer paint styles ────────────────────────────────────────────────────────
  const seaLayerPaint = {
    "line-color": ["match", ["get", "mode"], "sea", "#3b82f6", "#f59e0b"],
    "line-width": 2,
    "line-opacity": 0.85,
  };

  const seaLayerLayout = { "line-join": "round", "line-cap": "round" };

  // ── Map click handler ─────────────────────────────────────────────────────────
  const handleMapClick = (e) => {
    if (!drawingMode) return;
    const { lng, lat } = e.lngLat;
    const newWp = { lat, lon: lng, name: "", flag: false };
    const newWaypoints = [...drawnWaypoints, newWp];
    setDrawnWaypoints(newWaypoints);
    // Push to history
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push(newWaypoints);
    setHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
    setActiveDrawnWpt(newWaypoints.length - 1);
  };

  // ── Undo / Redo handlers ──────────────────────────────────────────────────────
  const handleUndo = () => {
    if (historyIndex === 0) return;
    const newIndex = historyIndex - 1;
    setHistoryIndex(newIndex);
    setDrawnWaypoints(history[newIndex]);
    setActiveDrawnWpt(null);
  };

  const handleRedo = () => {
    if (historyIndex >= history.length - 1) return;
    const newIndex = historyIndex + 1;
    setHistoryIndex(newIndex);
    setDrawnWaypoints(history[newIndex]);
    setActiveDrawnWpt(null);
  };

  // ── Point Info state (for drawn waypoints) ─────────────────────────────────────
  const [pointInfoPos, setPointInfoPos] = useState(null); // { lat, lon }
  const [pointInfoData, setPointInfoData] = useState(null); // { depth, ... }
  const [pointInfoLoading, setPointInfoLoading] = useState(false);

  const fetchPointInfo = async (lat, lon) => {
    setPointInfoPos({ lat, lon });
    setPointInfoData(null);
    setPointInfoLoading(true);
    try {
      const r = await fetch(`${API_URL}/point-info?lat=${lat}&lon=${lon}`);
      if (r.ok) {
        const data = await r.json();
        setPointInfoData(data);
      }
    } catch {}
    setPointInfoLoading(false);
  };

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: "flex", width: "100vw", height: "100vh" }}>

      {/* ── Sidebar ── */}
      <Sidebar
        segments={segments}
        loading={loading}
        error={error}
        drawingMode={drawingMode}
        onToggleDrawing={() => setDrawingMode((v) => !v)}
        drawnWaypoints={drawnWaypoints}
        onWaypointUpdate={(i, updates) => {
          const updated = drawnWaypoints.map((wp, idx) =>
            idx === i ? { ...wp, ...updates } : wp
          );
          setDrawnWaypoints(updated);
        }}
        onWaypointDelete={(i) => {
          const updated = drawnWaypoints.filter((_, idx) => idx !== i);
          setDrawnWaypoints(updated);
          const newHistory = history.slice(0, historyIndex + 1);
          newHistory.push(updated);
          setHistory(newHistory);
          setHistoryIndex(newHistory.length - 1);
          setActiveDrawnWpt(null);
        }}
        activeDrawnWpt={activeDrawnWpt}
        onSelectDrawnWpt={setActiveDrawnWpt}
        expeditionPlan={expeditionPlan}
        expeditionPlanLoading={expeditionPlanLoading}
        expeditionPlanError={expeditionPlanError}
        simulationMode={simulationMode}
        onSimulationToggle={() => {
          const entering = !simulationMode;
          setSimulationMode(entering);
          if (entering) {
            // Activation : positionner le catamaran sur La Rochelle
            setCatamaranPos(LA_ROCHELLE_POS);
            setSimPointIndex(1);
          } else {
            setCatamaranPos(null);
          }
        }}
        onAdvance={advanceCatamaranToNextMidpoint}
        canAdvance={simulationMode && simPointIndex < ITINERARY_POINTS.length - 1}
        legContext={legContext}
        onShowExport={() => setShowExport(true)}
      />

      {/* ── Export Sidebar ── */}
      {showExport && (
        <ExportSidebar
          segments={segments}
          drawnWaypoints={drawnWaypoints}
          onClose={() => setShowExport(false)}
        />
      )}

      {/* ── Map ── */}
      <div style={{ flex: 1, position: "relative" }}>

        {/* Wind widget */}
        {windData && (
          <div style={{
            position: "absolute",
            top: 12,
            right: 12,
            zIndex: 10,
            background: "rgba(15,23,42,0.82)",
            backdropFilter: "blur(6px)",
            borderRadius: 10,
            padding: "8px 13px",
            color: "#e2e8f0",
            fontSize: 13,
            display: "flex",
            alignItems: "center",
            gap: 8,
            boxShadow: "0 2px 12px rgba(0,0,0,0.3)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}>
            <WindDirectionArrow deg={windData.wind_direction_10m ?? 0} size={22} color="#93c5fd" />
            <span style={{ fontWeight: 600, color: "#93c5fd" }}>
              {windData.wind_speed_10m != null ? `${windData.wind_speed_10m} km/h` : "—"}
            </span>
            <span style={{ color: "#94a3b8", fontSize: 11 }}>
              {windData.wind_direction_10m != null
                ? getCardinalDirection(windData.wind_direction_10m)
                : ""}
            </span>
          </div>
        )}

        {/* Undo / Redo toolbar */}
        {drawingMode && (
          <div style={{
            position: "absolute",
            top: 12,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 10,
            display: "flex",
            gap: 8,
          }}>
            <button
              onClick={handleUndo}
              disabled={historyIndex === 0}
              title="Undo"
              style={{
                background: "rgba(15,23,42,0.85)",
                border: "1px solid rgba(255,255,255,0.15)",
                borderRadius: 8,
                padding: "6px 10px",
                color: historyIndex === 0 ? "#475569" : "#e2e8f0",
                cursor: historyIndex === 0 ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
              }}
            >
              <Undo2 size={16} />
            </button>
            <button
              onClick={handleRedo}
              disabled={historyIndex >= history.length - 1}
              title="Redo"
              style={{
                background: "rgba(15,23,42,0.85)",
                border: "1px solid rgba(255,255,255,0.15)",
                borderRadius: 8,
                padding: "6px 10px",
                color: historyIndex >= history.length - 1 ? "#475569" : "#e2e8f0",
                cursor: historyIndex >= history.length - 1 ? "not-allowed" : "pointer",
                display: "flex",
                alignItems: "center",
              }}
            >
              <Redo2 size={16} />
            </button>
          </div>
        )}

        <Map
          ref={mapRef}
          {...viewport}
          onMove={(evt) => setViewport(evt.viewState)}
          style={{ width: "100%", height: "100%" }}
          mapStyle="https://demotiles.maplibre.org/style.json"
          onClick={handleMapClick}
          cursor={drawingMode ? "crosshair" : "grab"}
        >
          <MaritimeLayers {...maritimeLayers} />

          {/* Route layer */}
          <Source id="route" type="geojson" data={routeGeoJSON}>
            <Layer
              id="route-line"
              type="line"
              paint={seaLayerPaint}
              layout={seaLayerLayout}
            />
          </Source>

          {/* Drawn waypoints layer */}
          {drawnWaypoints.length > 0 && (
            <Source id="drawn-waypoints" type="geojson" data={drawnWaypointsGeoJSON}>
              <Layer
                id="drawn-waypoints-layer"
                type="circle"
                paint={{
                  "circle-radius": 6,
                  "circle-color": "#f59e0b",
                  "circle-stroke-width": 2,
                  "circle-stroke-color": "#ffffff",
                }}
              />
            </Source>
          )}

          {/* Catamaran marker (simulation mode) */}
          {simulationMode && (
            <CatamaranMarker
              position={activeCatamaranPos}
              onDrag={(pos) => setCatamaranPos(pos)}
            />
          )}

          {/* Maritime layers panel (toggle buttons) */}
          <MaritimeLayersPanel {...maritimeLayers} />

          {/* ── ITINERARY POINT MARKERS ── */}
          {ITINERARY_POINTS.map((p, i) => {
            const offset = markerOffsets[i] || [0, 0];
            return (
              <Marker
                key={p.name}
                longitude={p.lon}
                latitude={p.lat}
                anchor="bottom"
                onClick={(e) => {
                  e.originalEvent.stopPropagation();
                  setSelectedPoint(selectedPoint?.name === p.name ? null : p);
                }}
              >
                <div
                  style={{ cursor: "pointer", userSelect: "none" }}
                  onMouseEnter={() => setHoveredPoint(i)}
                  onMouseLeave={() => setHoveredPoint(null)}
                >
                  {p.flag ? (
                    <span style={{ fontSize: 22, filter: "drop-shadow(0 1px 2px rgba(0,0,0,0.4))" }}>
                      {p.flag}
                    </span>
                  ) : (
                    <div style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      backgroundColor: "#0077ff",
                      border: "2px solid white",
                      boxShadow: "0 0 4px rgba(0,119,255,0.6)",
                    }} />
                  )}
                  {hoveredPoint === i && (
                    <div
                      style={{
                        position: "absolute",
                        bottom: "calc(100% + 7px)",
                        left: "50%",
                        transform: "translateX(-50%)",
                        background: "rgba(15,23,42,0.95)",
                        color: "#fff",
                        fontSize: "11px",
                        fontWeight: 600,
                        padding: "4px 9px",
                        borderRadius: "6px",
                        whiteSpace: "nowrap",
                        pointerEvents: "none",
                        boxShadow: "0 2px 8px rgba(0,0,0,0.35)",
                        letterSpacing: "0.02em",
                      }}
                    >
                      {p.name}
                    </div>
                  )}
                </div>
              </Marker>
            )
          })}

          {/* ── DRAWN WAYPOINT MARKERS ── */}
          {drawnWaypoints.map((wp, i) => (
            <Marker
              key={`drawn-${i}`}
              longitude={wp.lon}
              latitude={wp.lat}
              anchor="center"
              onClick={(e) => {
                e.originalEvent.stopPropagation();
                setActiveDrawnWpt(activeDrawnWpt === i ? null : i);
                fetchPointInfo(wp.lat, wp.lon);
              }}
            >
              <div
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: "50%",
                  backgroundColor: wp.flag ? "#f59e0b" : "#6366f1",
                  border: "2px solid white",
                  cursor: "pointer",
                  boxShadow: "0 0 5px rgba(0,0,0,0.4)",
                }}
              />
            </Marker>
          ))}

          {/* ── DRAWN WAYPOINT POPUP ── */}
          {activeDrawnWpt !== null && drawnWaypoints[activeDrawnWpt] && (
            <Popup
              longitude={drawnWaypoints[activeDrawnWpt].lon}
              latitude={drawnWaypoints[activeDrawnWpt].lat}
              anchor="top"
              onClose={() => setActiveDrawnWpt(null)}
              closeOnClick={false}
            >
              <div style={{ minWidth: 180, padding: "4px 2px" }}>
                <div style={{ fontWeight: 700, marginBottom: 6, fontSize: 13 }}>
                  Waypoint #{activeDrawnWpt + 1}
                </div>
                <input
                  type="text"
                  placeholder="Nom du point…"
                  value={drawnWaypoints[activeDrawnWpt].name}
                  onChange={(e) => {
                    const updated = drawnWaypoints.map((wp, idx) =>
                      idx === activeDrawnWpt ? { ...wp, name: e.target.value } : wp
                    );
                    setDrawnWaypoints(updated);
                  }}
                  style={{
                    width: "100%",
                    padding: "4px 6px",
                    borderRadius: 5,
                    border: "1px solid #cbd5e1",
                    fontSize: 12,
                    marginBottom: 6,
                    boxSizing: "border-box",
                  }}
                />
                <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={!!drawnWaypoints[activeDrawnWpt].flag}
                    onChange={(e) => {
                      const updated = drawnWaypoints.map((wp, idx) =>
                        idx === activeDrawnWpt ? { ...wp, flag: e.target.checked } : wp
                      );
                      setDrawnWaypoints(updated);
                    }}
                  />
                  Escale obligatoire
                </label>
                {/* Point info */}
                {pointInfoPos && (
                  <div style={{ marginTop: 8, fontSize: 11, color: "#475569" }}>
                    {pointInfoLoading ? (
                      <span>Chargement…</span>
                    ) : pointInfoData ? (
                      <span>Profondeur : {pointInfoData.depth != null ? `${pointInfoData.depth} m` : "—"}</span>
                    ) : null}
                  </div>
                )}
                <button
                  onClick={() => {
                    const updated = drawnWaypoints.filter((_, idx) => idx !== activeDrawnWpt);
                    setDrawnWaypoints(updated);
                    const newHistory = history.slice(0, historyIndex + 1);
                    newHistory.push(updated);
                    setHistory(newHistory);
                    setHistoryIndex(newHistory.length - 1);
                    setActiveDrawnWpt(null);
                  }}
                  style={{
                    marginTop: 8,
                    width: "100%",
                    padding: "4px 0",
                    borderRadius: 5,
                    border: "none",
                    background: "#fee2e2",
                    color: "#dc2626",
                    fontSize: 12,
                    cursor: "pointer",
                    fontWeight: 600,
                  }}
                >
                  Supprimer
                </button>
              </div>
            </Popup>
          )}

          {/* ── ITINERARY POINT POPUP ── */}
          {selectedPoint && (
            <Popup
              longitude={selectedPoint.lon}
              latitude={selectedPoint.lat}
              anchor="top"
              onClose={() => setSelectedPoint(null)}
              closeOnClick={false}
            >
              <div style={{ minWidth: 180, padding: "6px 4px" }}>
                <button
                  onClick={() => setSelectedPoint(null)}
                  style={{
                    position: "absolute",
                    top: 6,
                    right: 6,
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: "#64748b",
                    padding: 2,
                  }}
                >
                  <X size={14} />
                </button>
                <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 4, paddingRight: 20 }}>
                  {selectedPoint.flag} {selectedPoint.name}
                </div>
                {selectedPoint.description && (
                  <p style={{ fontSize: 12, color: "#475569", margin: 0, lineHeight: 1.4 }}>
                    {selectedPoint.description}
                  </p>
                )}
              </div>
            </Popup>
          )}

          {/* ── ITINERARY POINT MARKERS (dots only, no labels) ── */}
          {ITINERARY_POINTS.map((p, i) => {
            const offset = markerOffsets[i] || [0, 0];
            return (
              <Marker
                key={`dot-${p.name}`}
                longitude={p.lon}
                latitude={p.lat}
                anchor="center"
              >
                <div
                  onMouseEnter={() => setHoveredPoint(i)}
                  onMouseLeave={() => setHoveredPoint(null)}
                  style={{ position: "relative" }}
                >
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      backgroundColor: "#0077ff",
                      border: "2px solid white",
                      boxShadow: "0 0 4px rgba(0,119,255,0.6)",
                    }}
                  />
                  {hoveredPoint === i && (
                    <div
                      style={{
                        position: "absolute",
                        bottom: "calc(100% + 7px)",
                        left: "50%",
                        transform: "translateX(-50%)",
                        background: "rgba(15,23,42,0.95)",
                        color: "#fff",
                        fontSize: "11px",
                        fontWeight: 600,
                        padding: "4px 9px",
                        borderRadius: "6px",
                        whiteSpace: "nowrap",
                        pointerEvents: "none",
                        boxShadow: "0 2px 8px rgba(0,0,0,0.35)",
                        letterSpacing: "0.02em",
                      }}
                    >
                      {p.name}
                    </div>
                  )}
                </div>
              </Marker>
            )
          })}
        </Map>
      </div>
    </div>
  );
}

