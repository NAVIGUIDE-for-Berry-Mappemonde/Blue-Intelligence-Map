/**
 * NAVIGUIDE v2 — Export Sidebar (right panel)
 * Provides GeoJSON and KML export of the full expedition route + waypoints.
 * Also hosts mode toggles: Cabotage/Offshore, Onboarding/Cockpit, Dark/Light.
 */
import { useState, useEffect } from "react";
import { ChevronLeft, ChevronRight, Download, Anchor } from "lucide-react";

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

function ExportButton({ icon, label, sublabel, onClick, color }) {
  const colors = {
    blue:   "from-blue-600 to-blue-700 hover:from-blue-500 hover:to-blue-600 shadow-blue-900/40",
    teal:   "from-teal-600 to-teal-700 hover:from-teal-500 hover:to-teal-600 shadow-teal-900/40",
  };
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl
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

export function ExportSidebar({ segments, points, open, onToggle }) {
  const [exportStatus, setExportStatus] = useState(null); // "geojson" | "kml" | null

  // ── Mode states (false = default/left label, true = alternate/right label) ─
  const [isOffshore,  setIsOffshore]  = useState(false); // false=Cabotage, true=Offshore
  const [isCockpit,   setIsCockpit]   = useState(false); // false=Onboarding, true=Cockpit
  const [isLightMode, setIsLightMode] = useState(false); // false=Dark, true=Light

  // Apply dark/light class to <html> element
  useEffect(() => {
    const root = document.documentElement;
    if (isLightMode) {
      root.classList.add("light");
      root.classList.remove("dark");
    } else {
      root.classList.add("dark");
      root.classList.remove("light");
    }
  }, [isLightMode]);

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
      {/*
        Toggle button — when open it sits just outside the left edge of the
        panel (right-[322px]); when closed it stays at right-4 on the map.
      */}
      <button
        onClick={onToggle}
        className={`absolute top-4 z-30 bg-slate-900/95 border border-slate-700 text-white
          rounded-full w-9 h-9 flex items-center justify-center shadow-lg
          hover:bg-slate-800 transition-all duration-300 ${open ? "right-[322px]" : "right-4"}`}
        title={open ? "Hide export panel" : "Show export panel"}
      >
        {open ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>

      {/* Sidebar panel */}
      <div
        className={`absolute top-0 right-0 h-full z-20 flex flex-col bg-slate-900/97
          border-l border-slate-700/60 shadow-2xl transition-transform duration-300
          ${open ? "translate-x-0" : "translate-x-full"}`}
        style={{ width: 320 }}
      >

        {/* ── Mode Toggles ────────────────────────────────────────────────── */}
        <div className="px-4 pt-4 pb-3 border-b border-slate-700/60 flex-shrink-0 space-y-3">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
            Modes
          </div>
          <Toggle
            labelLeft="Cabotage"
            labelRight="Offshore"
            active={isOffshore}
            onChange={setIsOffshore}
          />
          <Toggle
            labelLeft="Onboarding"
            labelRight="Cockpit"
            active={isCockpit}
            onChange={setIsCockpit}
          />
          <Toggle
            labelLeft="Dark"
            labelRight="Light"
            active={isLightMode}
            onChange={setIsLightMode}
          />
        </div>

        {/* ── Route statistics ─────────────────────────────────────────────── */}
        <div className="px-4 py-3 border-b border-slate-700/60 flex-shrink-0">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Anchor size={11} className="text-blue-400" />
            Route Summary
          </div>
          <div className="bg-slate-800/60 rounded-xl px-3 py-1 border border-slate-700/40">
            <StatRow icon="🗺️" label="Total segments"    value={totalSegments} />
            <StatRow icon="⚓" label="Maritime legs"     value={maritimeSegs.length} />
            <StatRow icon="🛣️" label="Overland legs"     value={overlandSegs.length} />
            <StatRow icon="📍" label="Waypoints"         value={points.length} />
            <StatRow icon="🔢" label="Route points"      value={totalPoints.toLocaleString()} />
          </div>
        </div>

        {/* ── Export buttons ───────────────────────────────────────────────── */}
        <div className="flex-1 px-4 py-4 space-y-3 overflow-y-auto sidebar-scroll">

          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">
            Download
          </div>

          <ExportButton
            icon={<span className="text-base">📄</span>}
            label={exportStatus === "geojson" ? "Exported!" : "Export GeoJSON"}
            sublabel=""
            onClick={handleExportGeoJSON}
            color="blue"
          />

          <ExportButton
            icon={<span className="text-base">🌍</span>}
            label={exportStatus === "kml" ? "Exported!" : "Export KML"}
            sublabel=""
            onClick={handleExportKML}
            color="teal"
          />

        </div>

      </div>
    </>
  );
}
