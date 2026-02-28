/**
 * NAVIGUIDE v2 — Expedition Sidebar
 * Shows voyage statistics, LLM executive briefing, and critical alerts.
 * The Berry-Mappemonde card is an interactive route switcher with file import.
 */
import { useRef, useState } from "react";
import { ChevronLeft, ChevronRight, AlertTriangle, Navigation, Shield, Upload, X, Pencil, CheckCircle } from "lucide-react";
import { riskBadgeClass } from "../utils/riskColors";

/* ── Logo image paths (served from /public) ──────────────────────────────── */
const NAVIGUIDE_LOGO = "/logo-naviguide.png";
const BERRY_LOGO     = "/logo-berry-mappemonde.png";

/* ── File parsers ─────────────────────────────────────────────────────────── */

/** Parse a GeoJSON string → FeatureCollection preserving one Feature per LineString */
function parseGeoJSON(text) {
  const data     = JSON.parse(text);
  const features = [];

  const extract = (geometry, props = {}) => {
    if (!geometry) return;
    switch (geometry.type) {
      case "LineString":
        features.push({
          type: "Feature",
          properties: props,
          geometry: { type: "LineString", coordinates: geometry.coordinates.map(([lon, lat]) => [lon, lat]) },
        });
        break;
      case "MultiLineString":
        geometry.coordinates.forEach((line) =>
          features.push({
            type: "Feature",
            properties: props,
            geometry: { type: "LineString", coordinates: line.map(([lon, lat]) => [lon, lat]) },
          })
        );
        break;
      case "GeometryCollection":
        geometry.geometries.forEach((g) => extract(g, props));
        break;
      default:
        break;
    }
  };

  if (data.type === "FeatureCollection") {
    data.features.forEach((f) => extract(f.geometry, f.properties || {}));
  } else if (data.type === "Feature") {
    extract(data.geometry, data.properties || {});
  } else {
    extract(data);
  }

  return { type: "FeatureCollection", features };
}

/** Parse a KML string → FeatureCollection with one Feature per Placemark LineString */
function parseKML(text) {
  const doc      = new DOMParser().parseFromString(text, "application/xml");
  const features = [];

  // Each <Placemark> that contains a <LineString> becomes one Feature
  doc.querySelectorAll("Placemark").forEach((placemark) => {
    const nameEl = placemark.querySelector("name");
    const name   = nameEl?.textContent?.trim() || "";

    placemark.querySelectorAll("LineString coordinates").forEach((el) => {
      const coords = [];
      el.textContent.trim().split(/\s+/).forEach((pt) => {
        const [lonStr, latStr] = pt.split(",");
        const lon = parseFloat(lonStr);
        const lat = parseFloat(latStr);
        if (!isNaN(lon) && !isNaN(lat)) coords.push([lon, lat]);
      });
      if (coords.length > 0) {
        features.push({
          type: "Feature",
          properties: { name },
          geometry: { type: "LineString", coordinates: coords },
        });
      }
    });
  });

  return { type: "FeatureCollection", features };
}

/** Strip directory path and extension from a filename */
function stemName(filename) {
  return filename
    .replace(/\\/g, "/")
    .split("/")
    .pop()
    .replace(/\.(geojson|kml|json)$/i, "");
}

/* ── Sub-components ───────────────────────────────────────────────────────── */

function StatCard({ icon, label, value, sub }) {
  return (
    <div className="bg-slate-800/70 rounded-xl p-3 flex items-start gap-3">
      <div className="mt-0.5 text-slate-400">{icon}</div>
      <div className="min-w-0">
        <div className="text-xs text-slate-500 mb-0.5">{label}</div>
        <div className="text-sm font-semibold text-white truncate">{value}</div>
        {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
      </div>
    </div>
  );
}

function RiskBadge({ level }) {
  const cls = riskBadgeClass[level] || riskBadgeClass.UNKNOWN;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      {level || "UNKNOWN"}
    </span>
  );
}

function AlertItem({ alert }) {
  const colors = {
    CRITICAL: "border-red-700/60 bg-red-950/40",
    HIGH:     "border-orange-700/60 bg-orange-950/40",
  };
  const cls = colors[alert.risk_level] || "border-slate-700 bg-slate-800/40";
  return (
    <div className={`border rounded-lg p-2.5 ${cls}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-white truncate">{alert.waypoint}</span>
        <RiskBadge level={alert.risk_level} />
      </div>
      <div className="text-xs text-slate-400 mt-1 capitalize">
        Dominant: {alert.dominant_risk?.replace("_score", "") || "—"}
      </div>
    </div>
  );
}

/* ── BerryCard ────────────────────────────────────────────────────────────── */
/**
 * States:
 *  "berry-active"            – Berry highlighted (default). Click → "import-mode".
 *  "import-mode"             – Shows two import buttons. Berry route still shown.
 *  "file-active"             – Imported file is the active route. Shows Berry mini-btn + filename (highlighted).
 *  "berry-active-file-loaded"– Berry is active route, file is in memory. Shows Berry (highlighted) + filename.
 */
function BerryCard({ onRouteImport, onRouteSwitchToBerry, isDrawing, onDrawStart, onDrawFinish }) {
  const [cardMode, setCardMode]         = useState("berry-active");
  const [importedGeoJSON, setImportedGeoJSON] = useState(null); // FeatureCollection
  const [importedName, setImportedName]       = useState(null);
  const [importError, setImportError]         = useState(null);

  const geoJsonRef = useRef(null);
  const kmlRef     = useRef(null);

  /* ── File processing ──────────────────────────────────────────────────── */
  const processFile = (file) => {
    setImportError(null);
    const name = stemName(file.name);
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const text    = e.target.result;
        const isKml   = file.name.toLowerCase().endsWith(".kml");
        const geojson = isKml ? parseKML(text) : parseGeoJSON(text);

        if (geojson.features.length === 0) throw new Error("Aucune coordonnée trouvée");

        setImportedGeoJSON(geojson);
        setImportedName(name);
        setCardMode("file-active");
        onRouteImport(geojson);
      } catch (err) {
        setImportError(err.message);
      }
    };
    reader.readAsText(file);
  };

  /* ── Handlers ────────────────────────────────────────────────────────── */
  const handleCardClick = () => {
    if (cardMode === "berry-active" || cardMode === "berry-active-file-loaded") {
      setCardMode("import-mode");
    }
  };

  const handleImportFile = (ref) => ref.current?.click();

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
    e.target.value = ""; // allow re-import of same file
  };

  const handleBerryMiniClick = (e) => {
    e.stopPropagation();
    setCardMode("berry-active-file-loaded");
    onRouteSwitchToBerry();
  };

  const handleFileNameClick = (e) => {
    e.stopPropagation();
    if (importedGeoJSON) {
      setCardMode("file-active");
      onRouteImport(importedGeoJSON);
    }
  };

  const handleCancelImport = (e) => {
    e.stopPropagation();
    // Return to appropriate mode without importing
    setCardMode(importedGeoJSON ? "berry-active-file-loaded" : "berry-active");
  };

  const handleFinishDrawing = () => {
    const geojson = onDrawFinish(); // App stops drawing and returns built FeatureCollection
    if (geojson?.features?.length > 0) {
      setImportedGeoJSON(geojson);
      setImportedName("Custom Route");
      setCardMode("file-active");
      onRouteImport(geojson);
    } else {
      // Nothing drawn yet — just exit drawing mode
      setCardMode(importedGeoJSON ? "berry-active-file-loaded" : "berry-active");
    }
  };

  /* ── Render helpers ──────────────────────────────────────────────────── */

  // Glow ring for active state
  const glowCls   = "border-blue-500/70 bg-blue-950/30 shadow-[0_0_12px_2px_rgba(59,130,246,0.25)]";
  const normalCls = "border-slate-700/50 bg-slate-800/60";

  /* State: berry-active */
  if (cardMode === "berry-active") {
    return (
      <button
        onClick={handleCardClick}
        title="Cliquer pour importer une route"
        className={`w-full flex items-center gap-3 rounded-xl px-3 py-2 border
          transition-all duration-200 hover:border-blue-400/50 cursor-pointer ${glowCls}`}
      >
        <img src={BERRY_LOGO} alt="Berry-Mappemonde"
          className="h-12 w-auto object-contain rounded-lg flex-shrink-0" style={{ maxWidth: 90 }} />
        <div className="text-white font-bold text-sm leading-tight tracking-wide">BERRY-MAPPEMONDE</div>
      </button>
    );
  }

  /* State: import-mode */
  if (cardMode === "import-mode") {
    return (
      <div className={`rounded-xl px-3 py-2 border ${normalCls}`}>
        {/* Header row */}
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400 font-medium">Import or draw a route</span>
          <button onClick={handleCancelImport}
            className="text-slate-500 hover:text-slate-300 transition-colors" title="Cancel">
            <X size={13} />
          </button>
        </div>

        {/* Import buttons */}
        <div className="flex gap-2 mb-2">
          <button
            onClick={() => handleImportFile(geoJsonRef)}
            className="flex-1 flex items-center justify-center gap-1.5 bg-blue-600/20 hover:bg-blue-600/40
              border border-blue-500/40 rounded-lg px-2 py-2 text-xs text-blue-300 font-medium
              transition-all duration-150"
          >
            <Upload size={12} /> GeoJSON
          </button>
          <button
            onClick={() => handleImportFile(kmlRef)}
            className="flex-1 flex items-center justify-center gap-1.5 bg-teal-600/20 hover:bg-teal-600/40
              border border-teal-500/40 rounded-lg px-2 py-2 text-xs text-teal-300 font-medium
              transition-all duration-150"
          >
            <Upload size={12} /> KML
          </button>
        </div>

        {/* Draw / Finish button */}
        {isDrawing ? (
          <button
            onClick={handleFinishDrawing}
            className="w-full flex items-center justify-center gap-2 bg-green-600/30 hover:bg-green-600/50
              border border-green-500/50 rounded-lg px-2 py-2 text-xs text-green-300 font-semibold
              transition-all duration-150"
          >
            <CheckCircle size={12} /> Finish
          </button>
        ) : (
          <button
            onClick={() => onDrawStart()}
            className="w-full flex items-center justify-center gap-2 bg-violet-600/20 hover:bg-violet-600/40
              border border-violet-500/40 rounded-lg px-2 py-2 text-xs text-violet-300 font-medium
              transition-all duration-150"
          >
            <Pencil size={12} /> Draw your own route
          </button>
        )}

        {importError && (
          <p className="text-xs text-red-400 mt-1.5">{importError}</p>
        )}

        {/* Hidden file inputs */}
        <input ref={geoJsonRef} type="file" accept=".geojson,.json" className="hidden"
          onChange={handleFileChange} />
        <input ref={kmlRef}     type="file" accept=".kml"           className="hidden"
          onChange={handleFileChange} />
      </div>
    );
  }

  /* State: file-active */
  if (cardMode === "file-active") {
    return (
      <div className={`rounded-xl px-3 py-2 border ${glowCls}`}>
        <div className="flex items-center gap-2">
          {/* Berry mini-button */}
          <button
            onClick={handleBerryMiniClick}
            title="Revenir à la route Berry-Mappemonde"
            className="flex items-center gap-1.5 bg-slate-700/60 hover:bg-slate-600/60
              border border-slate-600/50 rounded-lg px-2 py-1 transition-all duration-150
              text-slate-400 hover:text-white flex-shrink-0"
          >
            <img src={BERRY_LOGO} alt="Berry" className="h-5 w-auto object-contain rounded" style={{ maxWidth: 28 }} />
            <span className="text-xs font-medium whitespace-nowrap">Berry</span>
          </button>

          {/* Active filename — highlighted */}
          <div className="flex-1 min-w-0 flex items-center gap-1.5">
            <span className="text-xs font-semibold text-blue-300 truncate" title={importedName}>
              {importedName}
            </span>
          </div>
        </div>
      </div>
    );
  }

  /* State: berry-active-file-loaded */
  if (cardMode === "berry-active-file-loaded") {
    return (
      <div className={`rounded-xl px-3 py-2 border ${glowCls}`}>
        <div className="flex items-center gap-2">
          {/* Berry active section — click to enter import-mode */}
          <button
            onClick={(e) => { e.stopPropagation(); setCardMode("import-mode"); }}
            title="Cliquer pour importer une nouvelle route"
            className="flex items-center gap-2 flex-shrink-0 hover:opacity-80 transition-opacity"
          >
            <img src={BERRY_LOGO} alt="Berry-Mappemonde"
              className="h-10 w-auto object-contain rounded-lg" style={{ maxWidth: 60 }} />
            <span className="text-white font-bold text-xs leading-tight tracking-wide whitespace-nowrap">
              BERRY-MAPPEMONDE
            </span>
          </button>

          {/* Divider */}
          <div className="w-px h-8 bg-slate-600/60 flex-shrink-0" />

          {/* Imported filename — clickable to re-activate */}
          <button
            onClick={handleFileNameClick}
            title={`Afficher la route : ${importedName}`}
            className="flex-1 min-w-0 text-left px-2 py-1 rounded-lg bg-slate-700/40
              hover:bg-blue-700/30 border border-slate-600/30 hover:border-blue-500/40
              transition-all duration-150"
          >
            <span className="text-xs text-slate-400 hover:text-blue-300 truncate block" title={importedName}>
              {importedName}
            </span>
          </button>
        </div>
      </div>
    );
  }

  return null;
}

/* ── Main component ───────────────────────────────────────────────────────── */

export function Sidebar({ plan, open, onToggle, onRouteImport, onRouteSwitchToBerry, isDrawing, onDrawStart, onDrawFinish, isCockpit, isOffshore }) {
  const stats    = plan?.voyage_statistics || {};
  const alerts   = plan?.critical_alerts   || [];
  const briefing = plan?.executive_briefing || "";

  return (
    <>
      {/*
        Toggle button.
        Offshore: larger (w-12 h-12, brighter border) for gloved use.
        Normal:   w-9 h-9.
      */}
      <button
        onClick={onToggle}
        className={`naviguide-sidebar-toggle absolute top-4 z-30 bg-slate-900/95 text-white
          rounded-full flex items-center justify-center shadow-lg
          hover:bg-slate-800 transition-all duration-300
          ${isOffshore
            ? "w-12 h-12 border-2 border-sky-400/70 shadow-sky-900/40"
            : "w-9 h-9 border border-slate-700"}
          ${open ? "left-[322px]" : "left-4"}`}
        title={open ? "Hide sidebar" : "Show expedition panel"}
      >
        {open
          ? <ChevronLeft  size={isOffshore ? 22 : 16} />
          : <ChevronRight size={isOffshore ? 22 : 16} />}
      </button>

      {/* Sidebar panel */}
      <div
        className={`naviguide-sidebar-panel absolute top-0 left-0 h-full z-20 flex flex-col bg-slate-900/97
          shadow-2xl transition-transform duration-300
          ${isOffshore
            ? "border-r-2 border-sky-400/40"
            : "border-r border-slate-700/60"}
          ${open ? "translate-x-0" : "-translate-x-full"}`}
        style={{ width: 320 }}
      >

        {/* ── Brand header ─────────────────────────────────────────────── */}
        <div className={`px-4 ${isCockpit ? "pt-3 pb-2" : "pt-4 pb-3"} border-b border-slate-700/60 flex-shrink-0`}>

          {/*
            COCKPIT: compact horizontal header — saves vertical space so all
            data panels can be visible simultaneously without scrolling.
            ONBOARDING: centred large logo with progressive guidance feel.
          */}
          {isCockpit ? (
            <div className="flex items-center gap-2 mb-2">
              <img src={NAVIGUIDE_LOGO} alt="NAVIGUIDE"
                className="h-8 w-8 object-contain" />
              <span className="text-white font-bold text-sm tracking-widest flex-1">NAVIGUIDE</span>
              <span className="text-xs font-semibold text-blue-300 bg-blue-950/40 px-2 py-0.5 rounded-full border border-blue-700/40">
                🎛️ Cockpit
              </span>
            </div>
          ) : (
            <div className="flex justify-center mb-3">
              <img
                src={NAVIGUIDE_LOGO}
                alt="NAVIGUIDE for Berry-Mappemonde"
                className="h-24 w-24 object-contain drop-shadow-lg"
              />
            </div>
          )}

          {/* Berry-Mappemonde interactive route card */}
          <BerryCard
            onRouteImport={onRouteImport}
            onRouteSwitchToBerry={onRouteSwitchToBerry}
            isDrawing={isDrawing}
            onDrawStart={onDrawStart}
            onDrawFinish={onDrawFinish}
          />
        </div>

        {/* ── Offshore banner — prominent high-contrast strip ──────────── */}
        {isOffshore && (
          <div className="px-4 py-2.5 flex-shrink-0 bg-sky-950/50 border-b-2 border-sky-500/50">
            <span className="font-bold text-sky-200 flex items-center gap-2 text-sm">
              ⚓ OFFSHORE — wind &amp; wave markers active
            </span>
          </div>
        )}

        {/*
          ── Stats grid ───────────────────────────────────────────────────
          COCKPIT: always visible even without plan (shows dashes).
          ONBOARDING: only appears once the AI plan has loaded.
        */}
        {(isCockpit || plan) && (
          <div className="px-4 py-3 border-b border-slate-700/60 flex-shrink-0">
            <div className="grid grid-cols-2 gap-2">
              <StatCard
                icon={<Navigation size={14} />}
                label="Total Distance"
                value={stats.total_distance_nm ? `${stats.total_distance_nm.toLocaleString()} nm` : "—"}
                sub={`${stats.total_segments || "—"} segments`}
              />
              <div className="bg-slate-800/70 rounded-xl p-3 flex flex-col gap-1">
                <div className="text-xs text-slate-500">Expedition Risk</div>
                <RiskBadge level={stats.expedition_risk_level} />
                <div className="text-xs text-slate-500 mt-0.5">
                  Score: {stats.overall_expedition_risk?.toFixed(2) ?? "—"}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Scrollable content ──────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto sidebar-scroll px-4 py-3 space-y-4">

          {/*
            ONBOARDING only: progressive "Getting Started" guide.
            Hidden in Cockpit — the user already knows the app.
          */}
          {!isCockpit && !plan && (
            <div className="rounded-xl border border-blue-700/30 bg-blue-950/20 p-3">
              <div className="text-xs font-semibold text-blue-300 mb-1.5 flex items-center gap-1.5">
                🧭 Getting Started
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                Click any point on the route to get wind, wave &amp; current data.
                Use the <strong className="text-slate-300">›</strong> button (top right) to switch modes or export your route.
              </p>
            </div>
          )}

          {/*
            AI Skipper Briefing.
            COCKPIT: always visible — shows placeholder when not yet loaded.
            ONBOARDING: shown only when plan data is available.
          */}
          {(isCockpit || briefing) && (
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Shield size={12} className="text-blue-400" />
                AI Skipper Briefing
              </div>
              <div className="bg-slate-800/50 rounded-xl p-3 border border-slate-700/50">
                <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-line">
                  {briefing || "Connect to the NAVIGUIDE orchestrator to generate your expedition briefing."}
                </p>
              </div>
            </div>
          )}

          {/*
            Critical Alerts.
            COCKPIT: always shown (with "no alerts" state for peace of mind).
            ONBOARDING: shown only when alerts exist.
          */}
          {(isCockpit || alerts.length > 0) && (
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <AlertTriangle size={12} className="text-orange-400" />
                Critical Alerts
              </div>
              {alerts.length > 0 ? (
                <div className="space-y-2">
                  {alerts.map((alert, i) => <AlertItem key={i} alert={alert} />)}
                </div>
              ) : (
                <div className="text-xs text-slate-500 py-2 px-3 bg-slate-800/30 rounded-xl border border-slate-700/40">
                  ✅ No critical alerts — route appears safe.
                </div>
              )}
            </div>
          )}

        </div>
      </div>
    </>
  );
}
