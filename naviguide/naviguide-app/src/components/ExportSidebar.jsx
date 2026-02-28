/**
 * NAVIGUIDE v2 — Export Sidebar (right panel)
 * Provides GeoJSON and KML export of the full expedition route + waypoints.
 * Also hosts mode toggles: Cabotage/Offshore, Onboarding/Cockpit, Dark/Light.
 * Language switcher (EN / FR) via LangContext.
 * Mode states are lifted to App.jsx — received as props.
 */
import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Anchor, Upload, Compass, CheckCircle2, TriangleAlert, Loader2 } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";

/* ── Polar constants ──────────────────────────────────────────────────────── */
const POLAR_API_URL      = import.meta.env.VITE_POLAR_API_URL ?? "http://localhost:8004";
const POLAR_EXPEDITION   = "berry-mappemonde-2026";
const POLAR_VMG_TWS_KEYS = ["8", "10", "12", "16", "20", "25"];

function kts(v) { return v != null ? `${Number(v).toFixed(1)} kt` : "—"; }
function deg(v) { return v != null ? `${Math.round(v)}°`          : "—"; }

function PolarStatusBadge({ status, detail }) {
  const cfg = {
    uploading: { icon: <Loader2 size={12} className="animate-spin" />, color: "text-blue-400",  bg: "bg-blue-900/30",  text: "Analyse…" },
    success:   { icon: <CheckCircle2 size={12} />,                     color: "text-green-400", bg: "bg-green-900/30", text: "Polaires chargées" },
    error:     { icon: <TriangleAlert size={12} />,                    color: "text-red-400",   bg: "bg-red-900/30",   text: "Échec" },
  };
  if (!status) return null;
  const c = cfg[status] ?? cfg.error;
  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg ${c.bg} ${c.color} text-xs`}>
      {c.icon}
      <span className="font-medium">{c.text}</span>
      {detail && <span className="text-slate-400 truncate ml-1">— {detail}</span>}
    </div>
  );
}

function PolarVmgRow({ tws, entry }) {
  const uw = entry?.upwind   ?? {};
  const dw = entry?.downwind ?? {};
  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/40 transition-colors">
      <td className="py-1 pl-2 pr-1 text-center font-bold text-blue-300 text-xs w-8">{tws}</td>
      <td className="py-1 px-1 text-center text-xs text-green-300">{deg(uw.twa)}</td>
      <td className="py-1 px-1 text-center text-xs text-slate-200">{kts(uw.speed)}</td>
      <td className="py-1 px-1 text-center text-xs font-semibold text-green-400">{kts(uw.vmg)}</td>
      <td className="py-1 px-0.5 text-slate-600 text-center text-xs">│</td>
      <td className="py-1 px-1 text-center text-xs text-amber-300">{deg(dw.twa)}</td>
      <td className="py-1 px-1 text-center text-xs text-slate-200">{kts(dw.speed)}</td>
      <td className="py-1 pr-2 pl-1 text-center text-xs font-semibold text-amber-400">{kts(dw.vmg)}</td>
    </tr>
  );
}

/* ── Helpers ──────────────────────────────────────────────────────────────── */

/** Trigger a file download in the browser */
function downloadFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** Build a GeoJSON FeatureCollection from segments + waypoints */
function buildGeoJSON(segments, points) {
  const features = [];

  // ── Route segments ────────────────────────────────────────────────────────
  segments.forEach((seg) => {
    if (!seg.coords || seg.coords.length === 0) return;
    features.push({
      type: "Feature",
      properties: {
        from:  seg.from?.name  ?? "",
        to:    seg.to?.name    ?? "",
        type:  seg.nonMaritime ? "overland" : "maritime",
      },
      geometry: {
        type: "LineString",
        coordinates: seg.coords, // already [lon, lat] pairs
      },
    });
  });

  // ── Waypoints ─────────────────────────────────────────────────────────────
  points.forEach((p) => {
    features.push({
      type: "Feature",
      properties: {
        name:       p.name,
        type:       "waypoint",
        point_type: p.flag ? "escale" : "intermediate",
      },
      geometry: {
        type: "Point",
        coordinates: [p.lon, p.lat],
      },
    });
  });

  return {
    type: "FeatureCollection",
    name: "NAVIGUIDE - Berry-Mappemonde Expedition",
    features,
  };
}

/** Build a KML string from segments + waypoints */
function buildKML(segments, points) {
  // KML colours: aabbggrr (alpha-blue-green-red)
  const maritimeColor = "ffff7700"; // blue-ish (#0077ff in BGR)
  const overlandColor = "ff888888"; // grey

  const escapeXml = (s) =>
    String(s)
      .replace(/&/g,  "&amp;")
      .replace(/</g,  "&lt;")
      .replace(/>/g,  "&gt;")
      .replace(/"/g,  "&quot;");

  /* ── Route placemarks ─────────────────────────────────────────────────── */
  const routePlacemarks = segments
    .filter((s) => s.coords && s.coords.length > 0)
    .map((s) => {
      const name  = escapeXml(`${s.from?.name ?? "?"} → ${s.to?.name ?? "?"}`);
      const style = s.nonMaritime ? "#overland-style" : "#maritime-style";
      const coords = s.coords.map(([lon, lat]) => `${lon},${lat},0`).join(" ");
      return `    <Placemark>
      <name>${name}</name>
      <styleUrl>${style}</styleUrl>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>${coords}</coordinates>
      </LineString>
    </Placemark>`;
    })
    .join("\n");

  /* ── Waypoint placemarks ──────────────────────────────────────────────── */
  // Escales use an inline <Style> with the flag data URI; intermediates use a shared style.
  const waypointPlacemarks = points
    .map((p) => {
      const name       = escapeXml(p.name);
      const isEscale   = Boolean(p.flag);
      const pointType  = isEscale ? "escale" : "intermediate";

      const styleBlock = isEscale
        ? `      <Style>
        <IconStyle>
          <scale>1.1</scale>
          <Icon>
            <href>${p.flag}</href>
          </Icon>
          <hotSpot x="0.5" y="0" xunits="fraction" yunits="fraction"/>
        </IconStyle>
        <LabelStyle><scale>0.85</scale></LabelStyle>
      </Style>`
        : `      <styleUrl>#intermediate-style</styleUrl>`;

      return `    <Placemark>
      <name>${name}</name>
${styleBlock}
      <ExtendedData>
        <Data name="naviguide_type"><value>${pointType}</value></Data>
      </ExtendedData>
      <Point>
        <coordinates>${p.lon},${p.lat},0</coordinates>
      </Point>
    </Placemark>`;
    })
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>NAVIGUIDE - Berry-Mappemonde Expedition</name>
    <description>Full expedition route exported from NAVIGUIDE</description>

    <!-- Styles -->
    <Style id="maritime-style">
      <LineStyle>
        <color>${maritimeColor}</color>
        <width>3</width>
      </LineStyle>
    </Style>
    <Style id="overland-style">
      <LineStyle>
        <color>${overlandColor}</color>
        <width>2</width>
      </LineStyle>
    </Style>
    <!-- Blue dot for intermediate routing waypoints -->
    <Style id="intermediate-style">
      <IconStyle>
        <color>ffff8800</color>
        <scale>0.6</scale>
        <Icon>
          <href>https://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>
        </Icon>
      </IconStyle>
      <LabelStyle><scale>0</scale></LabelStyle>
    </Style>

    <!-- Routes -->
    <Folder>
      <name>Routes</name>
${routePlacemarks}
    </Folder>

    <!-- Escales et waypoints -->
    <Folder>
      <name>Waypoints</name>
${waypointPlacemarks}
    </Folder>

  </Document>
</kml>`;
}

/* ── iOS-style Toggle ─────────────────────────────────────────────────────── */

function Toggle({ labelLeft, labelRight, active, onChange }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className={`text-xs font-medium transition-colors duration-200 ${!active ? "text-white" : "text-slate-500"}`}>
        {labelLeft}
      </span>
      <button
        onClick={() => onChange(!active)}
        className={`relative w-11 h-6 rounded-full transition-colors duration-300 focus:outline-none flex-shrink-0
          ${active ? "bg-blue-500" : "bg-slate-600"}`}
        role="switch"
        aria-checked={active}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow-md
            transition-transform duration-300 ${active ? "translate-x-5" : "translate-x-0"}`}
        />
      </button>
      <span className={`text-xs font-medium transition-colors duration-200 ${active ? "text-white" : "text-slate-500"}`}>
        {labelRight}
      </span>
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────────────────── */

function StatRow({ icon, label, value }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-700/40 last:border-0">
      <div className="flex items-center gap-2 text-xs text-slate-400">
        <span className="text-slate-500">{icon}</span>
        {label}
      </div>
      <span className="text-xs font-semibold text-white">{value}</span>
    </div>
  );
}

function ExportButton({ icon, label, onClick, color }) {
  const colors = {
    blue:   "from-blue-600 to-blue-700 hover:from-blue-500 hover:to-blue-600 shadow-blue-900/40",
    teal:   "from-teal-600 to-teal-700 hover:from-teal-500 hover:to-teal-600 shadow-teal-900/40",
  };
  return (
    <button
      onClick={onClick}
      className={`export-btn w-full flex items-center gap-3 px-4 py-3 rounded-xl
        bg-gradient-to-r ${colors[color] || colors.blue}
        text-white shadow-lg transition-all duration-200 active:scale-[0.98]`}
    >
      <div className="w-8 h-8 bg-white/15 rounded-lg flex items-center justify-center flex-shrink-0">
        {icon}
      </div>
      <div className="text-left">
        <div className="text-sm font-semibold leading-tight">{label}</div>
      </div>
      <Download size={14} className="ml-auto opacity-70" />
    </button>
  );
}

/* ── Main component ───────────────────────────────────────────────────────── */

export function ExportSidebar({
  segments, points, open, onToggle,
  // Mode props (state lives in App.jsx)
  isOffshore, isCockpit, isLightMode,
  onOffshoreChange, onCockpitChange, onLightModeChange,
  // Polar props (state lives in App.jsx)
  polarData, onPolarDataLoaded,
}) {
  const { lang, switchLang, t } = useLang();
  const [exportStatus, setExportStatus] = useState(null); // "geojson" | "kml" | null

  /* ── Polar upload state ──────────────────────────────────────────────────── */
  const [polarFile,         setPolarFile]         = useState(null);
  const [polarUploadStatus, setPolarUploadStatus] = useState(null);
  const [polarUploadDetail, setPolarUploadDetail] = useState("");
  const [isDragging,        setIsDragging]        = useState(false);
  const polarFileInputRef                         = useRef(null);

  useEffect(() => {
    if (polarFile) handlePolarUpload(polarFile);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [polarFile]);

  const handlePolarUpload = async (f) => {
    setPolarUploadStatus("uploading");
    setPolarUploadDetail("");
    const form = new FormData();
    form.append("file",          f);
    form.append("expedition_id", POLAR_EXPEDITION);
    try {
      const res  = await fetch(`${POLAR_API_URL}/api/v1/polar/upload`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
      onPolarDataLoaded({
        expedition_id: data.expedition_id,
        boat_name:     data.boat_name,
        grid_shape:    data.grid_shape,
        vmg_summary:   data.vmg_summary,
        created_at:    data.created_at,
      });
      setPolarUploadStatus("success");
      setPolarUploadDetail(data.boat_name);
    } catch (err) {
      setPolarUploadStatus("error");
      setPolarUploadDetail(String(err.message ?? err));
    }
  };

  const maritimeSegs  = segments.filter((s) => !s.nonMaritime && s.coords?.length > 0);
  const overlandSegs  = segments.filter((s) =>  s.nonMaritime && s.coords?.length > 0);
  const totalSegments = maritimeSegs.length + overlandSegs.length;

  /* Total coordinate count across all segments */
  const totalPoints = segments.reduce((acc, s) => acc + (s.coords?.length ?? 0), 0);

  /* ── Export handlers ─────────────────────────────────────────────────── */

  const handleExportGeoJSON = () => {
    setExportStatus("geojson");
    try {
      const geoJSON = buildGeoJSON(segments, points);
      const json    = JSON.stringify(geoJSON, null, 2);
      downloadFile(json, "naviguide-berry-mappemonde.geojson", "application/geo+json");
    } finally {
      setTimeout(() => setExportStatus(null), 1500);
    }
  };

  const handleExportKML = () => {
    setExportStatus("kml");
    try {
      const kml = buildKML(segments, points);
      downloadFile(kml, "naviguide-berry-mappemonde.kml", "application/vnd.google-earth.kml+xml");
    } finally {
      setTimeout(() => setExportStatus(null), 1500);
    }
  };

  return (
    <>
      {/* Toggle button — always visible on the map edge */}
      <button
        onClick={onToggle}
        className={`naviguide-sidebar-toggle absolute top-4 z-30 bg-slate-900/95 border border-slate-700 text-white
          rounded-full w-9 h-9 flex items-center justify-center shadow-lg
          hover:bg-slate-800 transition-all duration-300 ${open ? "right-[322px]" : "right-4"}`}
        title={open ? t("hideExportPanel") : t("showExportPanel")}
      >
        {open ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>

      {/* Sidebar panel */}
      <div
        className={`naviguide-sidebar-panel absolute top-0 right-0 h-full z-20 flex flex-col bg-slate-900/97
          border-l border-slate-700/60 shadow-2xl transition-transform duration-300
          ${open ? "translate-x-0" : "translate-x-full"}`}
        style={{ width: 320 }}
      >

        {/* ── Header: Language switcher (EN/FR) ─────────────────────────── */}
        <div className="px-4 pt-4 pb-1 flex-shrink-0">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              {t("language")}
            </span>
            <div className="flex bg-slate-800 rounded-full p-0.5 gap-0.5">
              <button
                onClick={() => switchLang("en")}
                className={`px-3 py-1 rounded-full text-xs font-bold transition-colors
                  ${lang === "en" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-white"}`}
              >
                EN
              </button>
              <button
                onClick={() => switchLang("fr")}
                className={`px-3 py-1 rounded-full text-xs font-bold transition-colors
                  ${lang === "fr" ? "bg-blue-600 text-white" : "text-slate-400 hover:text-white"}`}
              >
                FR
              </button>
            </div>
          </div>
        </div>

        {/* ── Mode Toggles ───────────────────────────────────────────────── */}
        <div className="px-4 pb-3 border-b border-slate-700/60 flex-shrink-0 space-y-3">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            {t("modes")}
          </div>
          <Toggle
            labelLeft={t("cabotage")}
            labelRight={t("offshore")}
            active={isOffshore}
            onChange={onOffshoreChange}
          />
          <Toggle
            labelLeft={t("onboarding")}
            labelRight={t("cockpit")}
            active={isCockpit}
            onChange={onCockpitChange}
          />
          <Toggle
            labelLeft={t("dark")}
            labelRight={t("light")}
            active={isLightMode}
            onChange={onLightModeChange}
          />
        </div>

        {/* ── Route statistics ─────────────────────────────────────────────── */}
        <div className="px-4 py-3 border-b border-slate-700/60 flex-shrink-0">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Anchor size={11} className="text-blue-400" />
            {t("routeSummary")}
          </div>
          <div className="bg-slate-800/60 rounded-xl px-3 py-1 border border-slate-700/40">
            <StatRow icon="🗺️" label={t("totalSegments")}  value={totalSegments} />
            <StatRow icon="⚓" label={t("maritimeLegs")}   value={maritimeSegs.length} />
            <StatRow icon="🛣️" label={t("overlandLegs")}   value={overlandSegs.length} />
            <StatRow icon="📍" label={t("waypoints")}      value={points.length} />
            <StatRow icon="🔢" label={t("routePoints")}    value={totalPoints.toLocaleString()} />
          </div>
        </div>

        {/* ── Export buttons ───────────────────────────────────────────────── */}
        <div className="flex-1 px-4 py-4 space-y-3 overflow-y-auto sidebar-scroll">

          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
            {t("download")}
          </div>

          <ExportButton
            icon={<span className="text-base">📄</span>}
            label={exportStatus === "geojson" ? t("exported") : t("exportGeoJSON")}
            onClick={handleExportGeoJSON}
            color="blue"
          />

          <ExportButton
            icon={<span className="text-base">🌍</span>}
            label={exportStatus === "kml" ? t("exported") : t("exportKML")}
            onClick={handleExportKML}
            color="teal"
          />

          {/* ── Polar Upload ───────────────────────────────────────────── */}
          <div className="pt-2 border-t border-slate-700/60 mt-2 space-y-3">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
              <Compass size={11} className="text-blue-400" />
              Chat
              {polarData?.boat_name && (
                <span className="ml-auto text-xs text-green-400 bg-green-900/30 px-2 py-0.5 rounded-full font-normal normal-case tracking-normal">
                  {polarData.boat_name}
                </span>
              )}
            </div>

            {/* Drop zone */}
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(e) => {
                e.preventDefault(); setIsDragging(false);
                const f = e.dataTransfer.files?.[0];
                const ok = [".pdf",".csv",".xlsx",".xls"];
                if (f && ok.some(ext => f.name.toLowerCase().endsWith(ext))) setPolarFile(f);
              }}
              onClick={() => polarFileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-1.5 p-4
                border-2 border-dashed rounded-xl cursor-pointer transition-colors
                ${isDragging
                  ? "border-blue-400 bg-blue-900/20"
                  : polarUploadStatus === "success"
                    ? "border-green-500/60 bg-green-900/10"
                    : polarUploadStatus === "uploading"
                      ? "border-blue-500/40 bg-blue-900/10"
                      : "border-slate-600 hover:border-slate-500 bg-slate-800/40"}`}
            >
              <input
                ref={polarFileInputRef}
                type="file"
                accept=".pdf,.csv,.xlsx,.xls"
                className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) setPolarFile(f); }}
              />
              {polarUploadStatus === "uploading"
                ? <Loader2 size={18} className="animate-spin text-blue-400" />
                : <Upload size={18} className={polarUploadStatus === "success" ? "text-green-400" : "text-slate-500"} />
              }
              {polarFile
                ? <span className="text-xs font-medium text-green-300 text-center break-all">{polarFile.name}</span>
                : <>
                    <span className="text-xs text-slate-400">Glissez un fichier polaire</span>
                    <span className="text-xs text-slate-600">PDF · CSV · XLSX</span>
                  </>
              }
            </div>

            <PolarStatusBadge status={polarUploadStatus} detail={polarUploadDetail} />

            {/* VMG table */}
            {polarData?.vmg_summary && (
              <div className="overflow-x-auto rounded-xl border border-slate-700/40 bg-slate-800/40">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-slate-800/80 border-b border-slate-700/60">
                      <th rowSpan={2} className="py-1.5 px-1.5 text-center text-blue-300 font-bold align-middle text-xs">
                        TWS<br /><span className="text-slate-500 font-normal">kt</span>
                      </th>
                      <th colSpan={3} className="py-1 px-1 text-center text-green-400 font-semibold text-xs border-r border-slate-700/40">↑ Près</th>
                      <th colSpan={3} className="py-1 px-1 text-center text-amber-400 font-semibold text-xs">↓ Portant</th>
                    </tr>
                    <tr className="bg-slate-800/60 border-b border-slate-700/60">
                      {["TWA","BS","VMG","TWA","BS","VMG"].map((h, i) => (
                        <th key={i} className={`py-1 px-1 font-medium text-slate-400 text-xs ${i===2?"border-r border-slate-700/40":""}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {POLAR_VMG_TWS_KEYS.map((tws) => (
                      <PolarVmgRow key={tws} tws={tws} entry={polarData.vmg_summary[tws]} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

        </div>

      </div>
    </>
  );
}
