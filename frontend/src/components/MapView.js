import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet.markercluster";
import api from "../api";

const TILE_URLS = {
  dark: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
  light: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
};

const FALLBACK_COLORS = {
  "MPA": "#00f0ff", "Conservation": "#39ff14", "Research": "#c084fc",
  "Fisheries": "#fbbf24", "Policy & Advocacy": "#f472b6", "Pollution": "#ff4a4a",
  "Coastal & Habitat": "#34d399", "Education": "#60a5fa", "Other": "#94a3b8",
};

// Phase 5 — MPA layer removed. LFP_COLORS/MPA_MIN_ZOOM constants deleted;
// see /api/mpa endpoint removal + mpa_cache collection drop.

// Refactor 2026-06 — Formalities mode = world EEZ choropleth + PoE markers.
const ZONE_COLORS = {
  non_generee: "#64748b", ia: "#fbbf24", ia_sans_source: "#fbbf24", erreur: "#ff4a4a",
};
const zoneStyle = (status) => {
  const s = status || "non_generee";
  return {
    color: ZONE_COLORS[s] || ZONE_COLORS.non_generee,
    weight: 1,
    opacity: s === "non_generee" ? 0.35 : 0.75,
    fillColor: ZONE_COLORS[s] || ZONE_COLORS.non_generee,
    fillOpacity: s === "ia" ? 0.16 : s === "ia_sans_source" ? 0.1 : s === "erreur" ? 0.1 : 0.04,
    dashArray: s === "ia_sans_source" ? "4 4" : null,
  };
};
const flagEmoji = (iso2) => {
  if (!iso2 || iso2.length !== 2) return "🌐";
  const cc = iso2.toUpperCase();
  return String.fromCodePoint(0x1f1e6 + cc.charCodeAt(0) - 65, 0x1f1e6 + cc.charCodeAt(1) - 65);
};

// Neutral route styling that reads on both dark and light basemaps.
// Two-layer stroke (dark casing + light main) gives contrast in every context.
const ROUTE_MAIN_COLOR = "#e2e8f0";     // slate-200 top line
const ROUTE_CASING_COLOR = "#0f172a";   // deep navy casing for contrast on light map
const ROUTE_MAIN_WEIGHT = 2.5;
const ROUTE_CASING_WEIGHT = 5;
const ESCALE_FILL = "#f8fafc";
const ESCALE_STROKE = "#0f172a";
const INTERMEDIATE_FILL = "#94a3b8";
const INTERMEDIATE_STROKE = "#475569";

export default function MapView({
  mode = "projects",
  projects,
  marinas,
  anchorages,
  showAnchorages = true,
  poeZones,
  poePorts,
  route,
  onSelectZone,
  flyToMarina,
  flyToZone,
  funderFilter,
  searchQuery,
  t,
  maxMarkers,
  minZoom,
  basemap,
  categories,
  categoryFilter,
}) {
  const mapRef = useRef(null);
  const mapObj = useRef(null);
  const clusterRef = useRef(null);
  const marinaClusterRef = useRef(null);
  const anchorClusterRef = useRef(null);
  const anchorSigRef = useRef("");
  const formalitiesClusterRef = useRef(null);
  const marinaMarkersById = useRef(new Map());
  const marinaSigRef = useRef("");
  const tileRef = useRef(null);
  const sigRef = useRef("");
  const zoomingRef = useRef(false);
  const pendingRef = useRef(null);
  const routeLayerRef = useRef(null);
  const routeLoadedRef = useRef(false);
  // Refactor 2026-06 — Formalities mode = EEZ polygons + PoE port markers
  const eezLayerRef = useRef(null);
  const eezLoadedRef = useRef(false);
  const eezLayersByMrgid = useRef(new Map());
  const zoneItemsRef = useRef(new Map());
  const poeClusterRef = useRef(null);
  const poeSigRef = useRef("");
  const [routeOn] = useState(true);

  // Popup content must reflect the CURRENT language + zone statuses — bindPopup(fn)
  // reads these refs at open time instead of capturing stale closures.
  const tRef = useRef(t);
  tRef.current = t;
  const onSelectZoneRef = useRef(onSelectZone);
  onSelectZoneRef.current = onSelectZone;

  const colorMap = {};
  (categories || []).forEach((c) => { colorMap[c.name] = c.color; });
  const colorOf = (g) => colorMap[g] || FALLBACK_COLORS[g] || "#00f0ff";

  useEffect(() => {
    if (mapObj.current) return;
    const WORLD = [[-85, -180], [85, 180]];
    const map = L.map(mapRef.current, {
      center: [22, 5],
      zoom: 2,
      zoomSnap: 0.25,
      minZoom: minZoom || 2,
      maxZoom: 18,
      zoomControl: true,
      maxBounds: WORLD,
      maxBoundsViscosity: 1.0,
    });
    tileRef.current = L.tileLayer(TILE_URLS.dark, {
      attribution: '&copy; Esri &copy; OpenStreetMap contributors',
      maxZoom: 16,
      noWrap: true,
      bounds: WORLD,
    }).addTo(map);
    // Single-world view: min zoom = world exactly fills the screen (no grey bands, no wrap)
    const fitMinZoom = () => {
      const mz = Math.max(minZoom || 2, map.getBoundsZoom(WORLD, true));
      map.setMinZoom(mz);
      if (map.getZoom() < mz) map.setZoom(mz, { animate: false });
    };
    fitMinZoom();
    map.on("resize", fitMinZoom);

    // Phase 5 — dedicated Leaflet pane for the route, drawn UNDER the clusters
    // and markers. Fixes "cluster 55 hovering over Europe hides the leg to Corsica".
    map.createPane("route");
    map.getPane("route").style.zIndex = 380;   // < markerPane (600) & tilePane (200 default)
    map.createPane("formalities-escales");
    map.getPane("formalities-escales").style.zIndex = 500;

    const cluster = L.markerClusterGroup({
      maxClusterRadius: 50,
      chunkedLoading: true,
      chunkInterval: 100,
      removeOutsideVisibleBounds: true,
      animate: false,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster" style="width:34px;height:34px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [34, 34],
      }),
    });
    // Marinas cluster — red-tinted, only added to the map when mode="marinas"
    const marinaCluster = L.markerClusterGroup({
      maxClusterRadius: 40,
      chunkedLoading: true,
      chunkInterval: 100,
      removeOutsideVisibleBounds: true,
      animate: false,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster-marina" style="width:32px;height:32px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [32, 32],
      }),
    });
    marinaClusterRef.current = marinaCluster;
    // Phase 8 — Anchorages cluster (teal), shown alongside marinas in marinas mode
    const anchorCluster = L.markerClusterGroup({
      maxClusterRadius: 40,
      chunkedLoading: true,
      chunkInterval: 100,
      removeOutsideVisibleBounds: true,
      animate: false,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster-anchorage" style="width:30px;height:30px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [30, 30],
      }),
    });
    anchorClusterRef.current = anchorCluster;
    // Refactor 2026-06 — Formalities mode: EEZ choropleth (VLIZ) + PoE cluster.
    // A single layerGroup wraps both so the mode-swap effect keeps working
    // through the historical `formalitiesClusterRef` handle.
    const poeCluster = L.markerClusterGroup({
      maxClusterRadius: 45,
      chunkedLoading: true,
      animate: false,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster-formalities" style="width:32px;height:32px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [32, 32],
      }),
    });
    poeClusterRef.current = poeCluster;
    const escH = (s) => String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    const zonePopupHtml = (mrgid, props) => {
      const t = tRef.current;
      const z = zoneItemsRef.current.get(mrgid) || props || {};
      const status = z.status || "non_generee";
      const col = ZONE_COLORS[status] || ZONE_COLORS.non_generee;
      const statusLabel = {
        non_generee: t("poeStatusNonGeneree"), ia: t("poeStatusIa"),
        ia_sans_source: t("poeStatusIaSansSource"), erreur: t("poeStatusErreur"),
      }[status];
      const flag = flagEmoji(z.iso2 || z.sov_iso2 || props?.iso2);
      const gen = z.generated_at ? String(z.generated_at).slice(0, 10) : null;
      const sources = (z.sources || []).map((s) => `
        <div style="margin-top:4px;font-size:11px;line-height:1.4;">
          <a href="${escH(s.url)}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;word-break:break-all;">${escH(s.url)}</a>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;">${escH(s.domain || "")}${s.collected_at ? " · " + escH(String(s.collected_at).slice(0, 10)) : ""}</div>
        </div>`).join("");
      const noSourceWarn = status === "ia_sans_source"
        ? `<div style="margin-top:6px;padding:4px 6px;background:rgba(255,74,74,0.08);border:1px solid rgba(255,74,74,0.35);color:#fecaca;font-size:10px;line-height:1.4;border-radius:2px;">⚠️ ${escH(t("poeNoSourceWarning"))}</div>`
        : "";
      const errHtml = z.last_error
        ? `<div style="margin-top:6px;font-size:10px;color:#fca5a5;">${escH(t("poeLastError"))}: ${escH(z.last_error)}</div>` : "";
      const body = status === "non_generee"
        ? `<div style="margin-top:8px;padding:8px;background:rgba(100,116,139,0.10);border:1px solid rgba(100,116,139,0.30);color:#94a3b8;font-size:11px;line-height:1.5;border-radius:2px;">${escH(t("poeZoneNotGenerated"))}</div>`
        : `${noSourceWarn}${errHtml}${sources ? `<div style="margin-top:8px;"><div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${escH(t("poeSourcesTitle"))}</div>${sources}</div>` : ""}`;
      const btnLabel = status === "non_generee" ? t("poeGenerateBtn") : t("poeRegenerateBtn");
      const genRunning = (window.__biPoeGenState || {})[mrgid] === "running";
      const btnHtml = genRunning
        ? `<button data-testid="poe-generate-btn" disabled
            style="font-size:10px;font-weight:600;color:#fbbf24;background:rgba(251,191,36,0.10);border:1px solid rgba(251,191,36,0.45);border-radius:2px;padding:3px 10px;opacity:0.7;cursor:wait;">
            ↻ ${escH(t("poeGenerating"))}
          </button>`
        : `<button data-testid="poe-generate-btn" onclick="window.__biGeneratePoeZone && window.__biGeneratePoeZone(${Number(mrgid)})"
            style="font-size:10px;font-weight:600;color:#fbbf24;background:rgba(251,191,36,0.10);border:1px solid rgba(251,191,36,0.45);border-radius:2px;padding:3px 10px;cursor:pointer;">
            ↻ ${escH(btnLabel)}
          </button>`;
      const polType = z.pol_type || props?.pol_type;
      return `
        <div style="min-width:260px;max-width:330px;font-family:Manrope,sans-serif;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;">${flag} ${escH(z.name || props?.name || props?.geoname || "")}</div>
          <div style="font-size:11px;color:#94a3b8;margin:3px 0 6px;">${escH(z.sovereign || props?.sovereign || "")}${polType && polType !== "200NM" ? " · " + escH(polType) : ""}</div>
          <div style="margin:4px 0 6px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${col};border:1px solid ${col}55;padding:2px 6px;border-radius:2px;">${escH(statusLabel)}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#f8fafc;border:1px solid #f8fafc55;padding:2px 6px;border-radius:2px;">⚓ ${z.poe_count || 0} ${escH(t("poePortsCount"))}</span>
            ${z.stale ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#fbbf24;border:1px solid rgba(251,191,36,0.5);background:rgba(251,191,36,0.1);padding:2px 6px;border-radius:2px;">⏰ ${escH(t("poeStale"))}</span>` : ""}
          </div>
          ${gen ? `<div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;">${escH(t("poeGeneratedAt"))}: ${escH(gen)}</div>` : ""}
          <div style="margin-top:8px;">
            ${btnHtml}
          </div>
          ${body}
          <div style="margin-top:8px;font-size:10px;color:#cbd5e1;">${escH(t("poeEezAttribution"))}</div>
        </div>`;
    };
    const eezLayer = L.geoJSON(null, {
      style: (feat) => zoneStyle(zoneItemsRef.current.get(feat?.properties?.mrgid)?.status),
      onEachFeature: (feat, lyr) => {
        const mrgid = feat.properties?.mrgid;
        eezLayersByMrgid.current.set(mrgid, lyr);
        lyr.bindPopup(() => zonePopupHtml(mrgid, feat.properties), {
          maxWidth: 350, minWidth: 260, maxHeight: 380, autoPan: true, autoPanPadding: [40, 40],
          className: "bi-formalities-popup",
        });
        lyr.on("click", () => {
          const cb = onSelectZoneRef.current;
          if (typeof cb === "function") cb(mrgid, null);
        });
        lyr.on("mouseover", () => { try { lyr.setStyle({ weight: 2, opacity: 0.95 }); } catch (_) {} });
        lyr.on("mouseout", () => { try { lyr.setStyle(zoneStyle(zoneItemsRef.current.get(mrgid)?.status)); } catch (_) {} });
      },
    });
    eezLayerRef.current = eezLayer;
    const formalitiesGroup = L.layerGroup([eezLayer, poeCluster]);
    formalitiesClusterRef.current = formalitiesGroup;
    // Add whichever cluster matches the initial mode; the mode-swap effect will fix it up
    // if the user is starting in another mode.
    if (mode === "marinas") map.addLayer(marinaCluster);
    else if (mode === "formalities") map.addLayer(formalitiesGroup);
    else map.addLayer(cluster);
    // Defer any layer rebuild until zoom animation fully ends (prevents orphan clusters / grey screens)
    map.on("zoomstart", () => { zoomingRef.current = true; });
    map.on("zoomend", () => {
      zoomingRef.current = false;
      if (pendingRef.current) {
        const fn = pendingRef.current;
        pendingRef.current = null;
        fn();
      }
      map.invalidateSize({ pan: false });
    });
    // Keep popups fully visible WITHOUT panning the map: shift the popup bubble itself
    const adjustPopup = (popup) => {
      const el = popup.getElement && popup.getElement();
      if (!el || !mapRef.current) return;
      const wrapper = el.querySelector(".leaflet-popup-content-wrapper");
      if (!wrapper) return;
      wrapper.style.transform = "";
      const mapRect = mapRef.current.getBoundingClientRect();
      const rect = wrapper.getBoundingClientRect();
      const pad = 10;
      let dx = 0, dy = 0;
      if (rect.left < mapRect.left + pad) dx = mapRect.left + pad - rect.left;
      else if (rect.right > mapRect.right - pad) dx = mapRect.right - pad - rect.right;
      if (rect.top < mapRect.top + pad) dy = mapRect.top + pad - rect.top;
      else if (rect.bottom > mapRect.bottom - pad) dy = mapRect.bottom - pad - rect.bottom;
      if (dx || dy) {
        wrapper.style.transition = "transform 0.15s ease";
        wrapper.style.transform = `translate(${dx}px, ${dy}px)`;
      }
    };
    map.on("popupopen", (e) => {
      adjustPopup(e.popup);
      setTimeout(() => adjustPopup(e.popup), 250);
      setTimeout(() => adjustPopup(e.popup), 800);
    });
    mapObj.current = map;
    clusterRef.current = cluster;
    // Debug hook — expose the map + all 3 clusters on window for headless
    // inspection. Non-visible, no runtime cost.
    if (typeof window !== "undefined") {
      window.__biDebug = { map, projects: cluster, marinas: marinaCluster, anchorages: anchorCluster, formalities: formalitiesGroup, eez: eezLayer, poe: poeCluster };
    }
  }, [minZoom]);

  useEffect(() => {
    if (tileRef.current) tileRef.current.setUrl(TILE_URLS[basemap] || TILE_URLS.dark);
  }, [basemap]);

  // ---------- Berry-Mappemonde route layer (static, official, always available) ----------
  useEffect(() => {
    const map = mapObj.current;
    if (!map || routeLoadedRef.current) return;
    routeLoadedRef.current = true;
    (async () => {
      let data;
      try {
        const res = await api.get("/route");
        data = res.data;
      } catch (e) {
        routeLoadedRef.current = false; // allow retry on next mount
        return;
      }
      const group = L.layerGroup();
      const feats = (data && data.features) || [];
      // Two-pass draw so lines sit UNDER waypoints: casings first, then main strokes, then waypoints
      const escales = [];
      const intermediates = [];
      feats.forEach((f) => {
        const g = f.geometry || {};
        const p = f.properties || {};
        if (g.type === "LineString") {
          const latlngs = g.coordinates.map(([lng, lat]) => [lat, lng]);
          const isOverland = p.type === "overland";
          // dark casing for contrast on light basemap — drawn in the "route" pane so
          // it sits UNDER the marker clusters (fixes cluster 55 over Europe hiding the leg).
          L.polyline(latlngs, {
            color: ROUTE_CASING_COLOR,
            weight: ROUTE_CASING_WEIGHT,
            opacity: 0.35,
            lineCap: "round",
            lineJoin: "round",
            interactive: false,
            fill: false,  // 2026-08-24 defensive — no fill on polyline
            pane: "route",
          }).addTo(group);
          // main stroke on top of the casing but still in the "route" pane
          const main = L.polyline(latlngs, {
            color: ROUTE_MAIN_COLOR,
            weight: ROUTE_MAIN_WEIGHT,
            opacity: 0.95,
            dashArray: isOverland ? "6 6" : null,
            lineCap: "round",
            lineJoin: "round",
            interactive: false,   // Phase 5: no hover tooltip on route segments
            fill: false,  // 2026-08-24 defensive — no fill on polyline
            pane: "route",
          });
          main.addTo(group);
        } else if (g.type === "Point") {
          const [lng, lat] = g.coordinates;
          const isEscale = p.point_type === "escale";
          if (isEscale) escales.push({ lat, lng, name: p.name });
          else intermediates.push({ lat, lng, name: p.name });
        }
      });
      // Intermediate waypoints — small muted dots (Phase 5: no tooltip, no popup — cleaner map)
      intermediates.forEach((w) => {
        const m = L.circleMarker([w.lat, w.lng], {
          radius: 2.5,
          color: INTERMEDIATE_STROKE,
          weight: 1,
          fillColor: INTERMEDIATE_FILL,
          fillOpacity: 0.9,
          interactive: false,
          pane: "route",
        });
        m.addTo(group);
      });
      // Escale waypoints — larger dots (Phase 5: no permanent label, popup on click only)
      escales.forEach((w) => {
        const m = L.circleMarker([w.lat, w.lng], {
          radius: 6,
          color: ESCALE_STROKE,
          weight: 2,
          fillColor: ESCALE_FILL,
          fillOpacity: 1,
          pane: "route",
        });
        m.bindPopup(
          () => `<div style="min-width:200px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:rgb(var(--accent-rgb));text-transform:uppercase;letter-spacing:0.1em;">${tRef.current(
              "routeWaypointEscale",
            )}</div>
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;margin-top:4px;">${
              w.name || ""
            }</div>
          </div>`,
          // keepInView removed 2026-06: combined with maxBounds it caused an
          // infinite pan loop (stack overflow in LineUtil.simplify) near ±180°.
          { maxWidth: 260, autoPan: true, autoPanPadding: [40, 40] },
        );
        m.addTo(group);
      });
      routeLayerRef.current = group;
      if (routeOn) group.addTo(map);
    })();
    // eslint-disable-next-line
  }, [t]);

  // Toggle route visibility on/off
  useEffect(() => {
    const map = mapObj.current;
    const layer = routeLayerRef.current;
    if (!map || !layer) return;
    if (routeOn) {
      if (!map.hasLayer(layer)) layer.addTo(map);
    } else if (map.hasLayer(layer)) {
      map.removeLayer(layer);
    }
  }, [routeOn]);

  // ---------- Marinas layer: rebuild markers when the marinas prop changes ----------
  useEffect(() => {
    const marinaCluster = marinaClusterRef.current;
    const map = mapObj.current;
    if (!marinaCluster || !map) return;
    const feats = (marinas && marinas.features) || [];
    const sig = feats.length + ":" + feats.map((f) => f.properties?.id).join(",");
    if (sig === marinaSigRef.current) return;
    marinaSigRef.current = sig;
    marinaCluster.clearLayers();
    marinaMarkersById.current.clear();

    // Priority-driven marker sizing (escales bigger than corridor)
    const RADIUS_BY_PRIO = { 1: 8, 2: 6, 3: 5 };
    const markers = feats.map((f) => {
      const [lon, lat] = f.geometry?.coordinates || [0, 0];
      const p = f.properties || {};
      const r = RADIUS_BY_PRIO[p.priority] || 5;
      const m = L.circleMarker([lat, lon], {
        radius: r,
        color: "#ff4a4a",
        weight: 2,
        fillColor: "#ff4a4a",
        fillOpacity: p.priority === 1 ? 0.85 : 0.55,
      });
      const tags = p.tags || {};
      const wp = p.nearest_waypoint || {};
      const vhf = tags.vhf_channel || tags.vhf;
      const phone = tags.phone || tags["contact:phone"];
      const website = tags.website || tags["contact:website"] || tags.url;
      const capacity = tags.capacity || tags["capacity:persons"] || tags["seamark:harbour:capacity"];
      const depth = tags.max_depth || tags.depth || tags["seamark:harbour:draught"];
      const fee = tags.fee;
      const enrSource = p.enrichment_source;
      const stars = (n) => (n && n >= 1 && n <= 5) ? "★".repeat(n) + "☆".repeat(5 - n) : null;
      const tagRow = (label, value, isLink = false) => {
        if (!value) return "";
        const disp = isLink
          ? `<a href="${value}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;">${value.replace(/^https?:\/\//, "").slice(0, 40)}</a>`
          : String(value);
        return `<div style="font-size:11px;color:#94a3b8;margin-top:3px;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${label}</span> ${disp}</div>`;
      };
      const enrichRow = (label, value) => {
        if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) return "";
        const disp = Array.isArray(value)
          ? value.map((v) => `<span style="display:inline-block;background:rgba(255,74,74,0.10);border:1px solid rgba(255,74,74,0.35);color:#fecaca;font-size:9px;font-family:'JetBrains Mono',monospace;padding:1px 5px;border-radius:2px;margin:1px 3px 1px 0;">${String(v)}</span>`).join("")
          : String(value);
        return `<div style="font-size:11px;color:#e2e8f0;margin-top:5px;line-height:1.35;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;display:block;margin-bottom:1px;">${label}</span>${disp}</div>`;
      };

      // Phase 7bis — bindPopup(FN) reads tRef.current lazily so FR ↔ EN
      // switching updates every next popup open, without rebuilding markers.
      m.bindPopup(
        () => {
          const t = tRef.current;
          const prioLabels = { 1: t("marinasPriority1"), 2: t("marinasPriority2"), 3: t("marinasPriority3") };
          const srcLabels = {
            openstreetmap: t("marinasSourceOSM"),
            shom: t("marinasSourceSHOM"),
            curated: t("marinasSourceCurated"),
          };
          const enrSourceLabel = {
            tinyfish: t("enrichSourceTinyfish"),
            openrouter: t("enrichSourceOpenrouter"),
            fallback: t("enrichSourceFallback"),
          }[enrSource] || "";
          const enrichBlock = p.enriched
            ? `<div style="margin-top:8px;padding:6px 7px;background:rgba(255,74,74,0.06);border:1px solid rgba(255,74,74,0.30);border-radius:3px;">
                <div style="display:flex;align-items:center;gap:5px;margin-bottom:2px;">
                  <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#ff4a4a;text-transform:uppercase;letter-spacing:0.1em;">◆ ${t("marinasEnriched")}</span>
                  ${enrSourceLabel ? `<span style="font-size:9px;color:#94a3b8;font-family:'JetBrains Mono',monospace;">${enrSourceLabel}</span>` : ""}
                  ${p.stale ? `<span style="font-size:9px;color:#fbbf24;font-family:'JetBrains Mono',monospace;">· ${t("enrichStale")}</span>` : ""}
                </div>
                ${enrichRow(t("enrichVHF"), p.canal_vhf)}
                ${enrichRow(t("enrichBerths"), p.places_visiteurs)}
                ${enrichRow(t("enrichDraft"), p.tirant_eau_max_metres)}
                ${enrichRow(t("enrichWeather"), stars(p.score_protection_meteo))}
                ${enrichRow(t("enrichServices"), p.services_disponibles)}
                ${enrichRow(t("enrichPhone"), p.telephone_capitainerie)}
                ${enrichRow(t("enrichReview"), p.resume_avis)}
              </div>`
            : `<div style="margin-top:8px;font-size:10px;color:#94a3b8;font-family:'JetBrains Mono',monospace;font-style:italic;">${t("enrichNever")}</div>`;
          return `<div style="min-width:240px;max-width:300px;">
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${p.name || ""}</div>
            <div style="margin:6px 0;display:flex;gap:5px;flex-wrap:wrap;">
              <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#ff4a4a;border:1px solid #ff4a4a55;padding:2px 6px;border-radius:2px;">P${p.priority} · ${prioLabels[p.priority] || ""}</span>
              <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;border:1px solid #33415555;padding:2px 6px;border-radius:2px;">${srcLabels[p.source] || p.source || ""}</span>
            </div>
            <div style="font-size:11px;color:#c084fc;margin:3px 0 6px;">
              <span style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;">${t("marinasNearest")}</span>
              ${wp.name || "—"} · ${(wp.distance_nm ?? 0).toFixed(1)} ${t("marinasDistanceNM")}
            </div>
            ${tagRow(t("marinasVHF"), vhf)}
            ${tagRow(t("marinasCapacity"), capacity)}
            ${tagRow(t("marinasDepth"), depth)}
            ${tagRow(t("marinasFee"), fee)}
            ${tagRow(t("marinasPhone"), phone)}
            ${tagRow(t("marinasWebsite"), website, true)}
            ${enrichBlock}
            <div style="margin-top:8px;display:flex;gap:5px;align-items:center;">
              <button onclick="window.__biEnrichMarina && window.__biEnrichMarina('${p.id}')" data-testid="popup-enrich-btn" style="font-size:10px;font-weight:600;color:#ff4a4a;background:rgba(255,74,74,0.10);border:1px solid rgba(255,74,74,0.45);border-radius:2px;padding:3px 10px;cursor:pointer;">◆ ${t("enrichAction")}</button>
              <span style="font-size:9px;color:#64748b;">${p.osm_id ? "OSM " + p.osm_id + " · " : ""}${t("marinasFetchedAt")}: ${(p.fetched_at || "").slice(0, 10)}</span>
            </div>
          </div>`;
        },
        { maxWidth: 320, maxHeight: 400, autoPan: true, autoPanPadding: [40, 40] },
      );
      marinaMarkersById.current.set(p.id, m);
      return m;
    });
    marinaCluster.addLayers(markers);
  }, [marinas]);

  // ---------- Phase 8 — Anchorages layer: rebuild when the anchorages prop changes ----------
  useEffect(() => {
    const anchorCluster = anchorClusterRef.current;
    const map = mapObj.current;
    if (!anchorCluster || !map) return;
    const feats = (anchorages && anchorages.features) || [];
    const sig = feats.length + ":" + feats.map((f) => f.properties?.id).join(",");
    if (sig === anchorSigRef.current) return;
    anchorSigRef.current = sig;
    anchorCluster.clearLayers();

    const TYPE_KEY = { bay: "anchoragesTypeBay", anchorage: "anchoragesTypeAnchorage", anchor_berth: "anchoragesTypeBerth" };
    const markers = feats.map((f) => {
      const [lon, lat] = f.geometry?.coordinates || [0, 0];
      const p = f.properties || {};
      const m = L.circleMarker([lat, lon], {
        radius: p.priority === 1 ? 7 : 5,
        color: "#2dd4bf",
        weight: 2,
        fillColor: "#2dd4bf",
        fillOpacity: p.priority === 1 ? 0.8 : 0.5,
      });
      const tags = p.tags || {};
      const wp = p.nearest_waypoint || {};
      const row = (label, value) => {
        if (!value) return "";
        return `<div style="font-size:11px;color:#94a3b8;margin-top:3px;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${label}</span> ${String(value)}</div>`;
      };
      m.bindPopup(
        () => {
          const t = tRef.current;
          const typeLabel = t(TYPE_KEY[p.anchorage_type] || "anchoragesTypeAnchorage");
          const depth = tags["seamark:anchorage:depth"] || tags.depth || tags.max_depth;
          const holding = tags["seamark:anchorage:holding_ground"] || tags.holding_ground;
          return `<div style="min-width:220px;max-width:290px;">
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">⚓ ${p.name || ""}</div>
            <div style="margin:6px 0;display:flex;gap:5px;flex-wrap:wrap;">
              <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#2dd4bf;border:1px solid #2dd4bf55;padding:2px 6px;border-radius:2px;">${typeLabel}</span>
              <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;border:1px solid #33415555;padding:2px 6px;border-radius:2px;">P${p.priority} · OSM</span>
            </div>
            <div style="font-size:11px;color:#c084fc;margin:3px 0 6px;">
              <span style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;">${t("marinasNearest")}</span>
              ${wp.name || "—"} · ${(wp.distance_nm ?? 0).toFixed(1)} ${t("marinasDistanceNM")}
            </div>
            ${row(t("anchoragesCategory"), tags.anchorage_category_label)}
            ${row(t("marinasDepth"), depth)}
            ${row(t("anchoragesHolding"), holding)}
            ${row(t("anchoragesShelter"), tags.shelter)}
            ${row("Description", tags.description ? String(tags.description).slice(0, 160) : null)}
            <div style="margin-top:7px;font-size:9px;color:#64748b;">${p.osm_id ? "OSM " + p.osm_id + " · " : ""}${t("marinasFetchedAt")}: ${(p.fetched_at || "").slice(0, 10)}</div>
          </div>`;
        },
        { maxWidth: 300, maxHeight: 360, autoPan: true, autoPanPadding: [40, 40] },
      );
      return m;
    });
    anchorCluster.addLayers(markers);
  }, [anchorages]);

  // ---------- Mode swap: attach the right cluster, hide the others (Phase 4A → Phase 8) ----------
  useEffect(() => {
    const map = mapObj.current;
    const proj = clusterRef.current;
    const mar = marinaClusterRef.current;
    const anch = anchorClusterRef.current;
    const formCluster = formalitiesClusterRef.current;
    if (!map || !proj || !mar || !formCluster) return;
    // Detach everything first, then attach only the layer(s) for the current mode.
    if (map.hasLayer(proj)) map.removeLayer(proj);
    if (map.hasLayer(mar)) map.removeLayer(mar);
    if (anch && map.hasLayer(anch)) map.removeLayer(anch);
    if (map.hasLayer(formCluster)) map.removeLayer(formCluster);
    if (mode === "marinas") {
      map.addLayer(mar);
      if (anch && showAnchorages) map.addLayer(anch);
    } else if (mode === "formalities") {
      map.addLayer(formCluster);
    } else {
      map.addLayer(proj);
    }
    map.closePopup();
  }, [mode, showAnchorages]);

  // ---------- FlyTo signal from MarinasPanel ----------
  useEffect(() => {
    if (!flyToMarina) return;
    const map = mapObj.current;
    if (!map) return;
    const m = marinaMarkersById.current.get(flyToMarina.id);
    map.flyTo([flyToMarina.lat, flyToMarina.lon], Math.max(map.getZoom(), 10), { duration: 1.0 });
    setTimeout(() => { if (m) m.openPopup(); }, 1100);
  }, [flyToMarina]);

  // ---------- Refactor 2026-06 — Formalities mode: EEZ choropleth + PoE markers ----------
  // Lazy-load the EEZ polygons once (heavy file) when formalities mode is first opened.
  useEffect(() => {
    if (mode !== "formalities" || eezLoadedRef.current) return;
    const layer = eezLayerRef.current;
    if (!layer) return;
    eezLoadedRef.current = true;
    (async () => {
      try {
        const res = await api.get("/poe/zones/geojson");
        layer.addData(res.data);
      } catch (e) {
        // 404 until the referential is built — retry on the next zones refresh
        eezLoadedRef.current = false;
      }
    })();
  }, [mode, poeZones]);

  // Restyle polygons + refresh any open popup whenever zone statuses change.
  useEffect(() => {
    const byMrgid = new Map();
    for (const z of poeZones || []) byMrgid.set(z.mrgid, z);
    zoneItemsRef.current = byMrgid;
    const layer = eezLayerRef.current;
    if (layer) {
      layer.eachLayer((lyr) => {
        const mrgid = lyr.feature?.properties?.mrgid;
        try { lyr.setStyle(zoneStyle(byMrgid.get(mrgid)?.status)); } catch (_) { /* noop */ }
      });
    }
    const map = mapObj.current;
    const popup = map?._popup;
    if (popup && typeof popup.update === "function") {
      try { popup.update(); } catch (_) { /* noop */ }
    }
  }, [poeZones]);

  // PoE port markers (amber dots, clustered).
  useEffect(() => {
    const cluster = poeClusterRef.current;
    if (!cluster) return;
    const feats = poePorts?.features || [];
    const sig = feats.map((f) => `${f.properties.id}|${f.properties.validated ? 1 : 0}`).join(",");
    if (sig === poeSigRef.current && cluster.getLayers().length) return;
    poeSigRef.current = sig;
    cluster.clearLayers();
    const escH = (s) => String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    const markers = feats.map((f) => {
      const [lon, lat] = f.geometry.coordinates;
      const p = f.properties;
      const m = L.marker([lat, lon], {
        icon: L.divIcon({
          html: `<div style="width:14px;height:14px;border-radius:50%;background-color:#fbbf24;border:1.5px solid #0b1220;box-sizing:border-box;"></div>`,
          className: "bi-status-icon",
          iconSize: [14, 14],
          iconAnchor: [7, 7],
          popupAnchor: [0, -7],
        }),
      });
      m.bindPopup(() => {
        const t = tRef.current;
        const valid = p.validated
          ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#39ff14;border:1px solid rgba(57,255,20,0.45);padding:2px 6px;border-radius:2px;">✓ ${escH(t("poeValidated"))}</span>`
          : `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#fbbf24;border:1px solid rgba(251,191,36,0.45);padding:2px 6px;border-radius:2px;">⚠ ${escH(t("poeOutsideEez"))}${p.distance_km != null ? " ~" + escH(p.distance_km) + " km" : ""}</span>`;
        const srcs = (p.source_urls || []).slice(0, 3).map((u) => `
          <div style="margin-top:3px;font-size:10px;"><a href="${escH(u)}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;word-break:break-all;">${escH(u)}</a></div>`).join("");
        return `<div style="min-width:230px;max-width:300px;font-family:Manrope,sans-serif;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">⚓ ${escH(p.name)}</div>
          <div style="font-size:11px;color:#94a3b8;margin:3px 0 5px;">${escH(p.city || "")}${p.city ? " · " : ""}${flagEmoji(p.country_iso2)} ${escH(p.zone_name || "")}</div>
          <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:5px;">${valid}
            <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;border:1px solid #33415555;padding:2px 6px;border-radius:2px;">${escH(p.geocode_source || t("poeNotGeocoded"))}</span>
          </div>
          ${p.note ? `<div style="font-size:11px;color:#e2e8f0;line-height:1.4;margin-bottom:5px;">${escH(p.note)}</div>` : ""}
          ${srcs ? `<div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-top:4px;">${escH(t("poeSourcesTitle"))}</div>${srcs}` : ""}
          <div style="margin-top:7px;font-size:9px;color:#64748b;">${escH(t("poeGeocodeAttribution"))}${p.extracted_at ? " · " + escH(String(p.extracted_at).slice(0, 10)) : ""}</div>
        </div>`;
      }, { maxWidth: 310, maxHeight: 340, autoPan: true, autoPanPadding: [40, 40] });
      return m;
    });
    cluster.addLayers(markers);
  }, [poePorts]);

  // ---------- FlyTo signal from FormalitiesPanel (EEZ row click) ----------
  useEffect(() => {
    if (!flyToZone) return;
    const map = mapObj.current;
    if (!map) return;
    const [w, s, e, n] = flyToZone.bbox;
    const anchor = flyToZone.anchor; // [lon, lat] — representative point (antimeridian-safe)
    const anchorLatLng = anchor ? L.latLng(anchor[1], anchor[0]) : null;
    const open = () => {
      const lyr = eezLayersByMrgid.current.get(flyToZone.mrgid);
      if (!lyr) return;
      let at = anchorLatLng;
      if (at) {
        // maxBounds (viscosity 1) can clamp the fly for antimeridian zones
        // (Fiji at 175°E): re-anchor the popup inside the effective viewport
        // so it never opens off-screen.
        const b = map.getBounds();
        const mLng = (b.getEast() - b.getWest()) * 0.12;
        const mLat = (b.getNorth() - b.getSouth()) * 0.12;
        at = L.latLng(
          Math.min(Math.max(at.lat, b.getSouth() + mLat), b.getNorth() - mLat),
          Math.min(Math.max(at.lng, b.getWest() + mLng), b.getEast() - mLng),
        );
      }
      try { lyr.openPopup(at || undefined); } catch (_) { /* not attached yet */ }
    };
    map.once("moveend", open);
    try {
      if (e - w > 350 && anchorLatLng) {
        // Zone spanning the antimeridian (Fiji, Russia…): fitBounds would show
        // the whole world — fly to the representative point instead.
        map.flyTo(anchorLatLng, 5, { duration: 0.8 });
      } else {
        map.flyToBounds(L.latLngBounds([s, w], [n, e]), { duration: 0.8, maxZoom: 7, padding: [30, 30] });
      }
    } catch (_) { /* noop */ }
    const safety = setTimeout(open, 1400);
    return () => { clearTimeout(safety); map.off("moveend", open); };
  }, [flyToZone]);

  // ---------- Lang change → refresh any currently open popup ----------
  // i18n lazy-binding fix (2026-08-24): when the user toggles FR ↔ EN, if a
  // popup is already open its content is static HTML (built at the previous
  // language). We call `popup.update()` which re-invokes the bindPopup(fn)
  // content function — that function now reads `tRef.current` (updated at
  // every render above) and returns HTML in the new language. This does NOT
  // touch any marker or cluster — zero rebuild, zero DOM chum on markers.
  useEffect(() => {
    const map = mapObj.current;
    if (!map) return;
    const popup = map._popup;
    if (popup && typeof popup.update === "function") {
      try { popup.update(); } catch (_) { /* map/popup detached — noop */ }
    }
  }, [t]);

  useEffect(() => {
    const cluster = clusterRef.current;
    const map = mapObj.current;
    if (!cluster || !map) return;
    const q = (searchQuery || "").toLowerCase();
    const features = (projects.features || [])
      .filter((f) => (funderFilter === "All" || (f.properties.funder || "").includes(funderFilter)) &&
        (categoryFilter === "All" || f.properties.category_group === categoryFilter) &&
        (!q || `${f.properties.title} ${f.properties.description} ${f.properties.funder} ${f.properties.location || ""}`.toLowerCase().includes(q)))
      .slice(0, maxMarkers || 1000);
    // Skip rebuild if the visible set is unchanged — keeps open popups alive
    const sig = `${features.length}|${funderFilter}|${categoryFilter}|${q}|${features.map((f) => f.properties.id).join(",")}`;
    if (sig === sigRef.current) return;
    sigRef.current = sig;

    const apply = () => {
      map.closePopup();
      cluster.clearLayers();
      const markers = features.map((f) => {
        const [lon, lat] = f.geometry.coordinates;
        const p = f.properties;
        const col = colorOf(p.category_group);
        const marker = L.circleMarker([lat, lon], {
          radius: 7,
          color: col,
          weight: 2,
          fillColor: col,
          fillOpacity: 0.6,
        });
        const img = p.image ? `<img src="${p.image}" referrerpolicy="no-referrer" style="width:100%;height:110px;object-fit:cover;border-radius:3px;margin-bottom:8px;" onerror="this.remove()" />` : "";
        // i18n lazy-binding fix (2026-08-24): bindPopup(FN) so the HTML is
        // rebuilt at each open with the CURRENT `t` via `tRef.current`. This
        // lets FR ↔ EN switching update every future popup open without
        // rebuilding markers, and allows the lang-change refresh effect
        // (below) to refresh an ALREADY-open popup via `popup.update()`.
        marker.bindPopup(() => {
          const t = tRef.current;
          const snapped = p.snapped ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#fbbf24;border:1px solid #fbbf2455;padding:1px 5px;border-radius:2px;margin-left:6px;">${t("snappedBadge")}</span>` : "";
          const cat = p.category_group ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${col};border:1px solid ${col}55;padding:1px 5px;border-radius:2px;">${t("cat_" + p.category_group)}</span>` : "";
          return `
          <div style="min-width:220px;max-width:270px;">
            ${img}
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${p.title}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#c084fc;margin:4px 0;">${p.funder}${snapped}</div>
            <div style="margin:2px 0 6px;">${cat}</div>
            <div style="font-size:11px;color:#94a3b8;line-height:1.45;margin-bottom:6px;">${p.description || ""}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;gap:5px;flex-wrap:wrap;">
              <a href="${p.url}" target="_blank" rel="noreferrer" style="font-size:11px;color:#00f0ff;font-weight:600;text-decoration:none;">${t("viewProject")} →</a>
              <button onclick="window.__biEnrichProject && window.__biEnrichProject('${p.id}')" data-testid="popup-project-enrich-btn" style="font-size:10px;font-weight:600;color:#00f0ff;background:rgba(0,240,255,0.08);border:1px solid rgba(0,240,255,0.4);border-radius:2px;padding:2px 8px;cursor:pointer;">↻ ${t("projectEnrich")}</button>
              ${p.s_ocean != null ? `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#39ff14;">S<sub>ocean</sub> ${p.s_ocean}</span>` : ""}
            </div>
          </div>
        `;
        }, { maxWidth: 280, maxHeight: 400, autoPan: true, autoPanPadding: [40, 40] });
        return marker;
      });
      cluster.addLayers(markers);
    };

    if (zoomingRef.current) {
      pendingRef.current = apply;
    } else {
      apply();
    }
    // i18n lazy-binding fix (2026-08-24): deps are DATA-ONLY. `t` is
    // intentionally excluded — the popup content function reads
    // `tRef.current` at open time, so language changes never trigger a
    // marker rebuild.
  }, [projects, funderFilter, categoryFilter, searchQuery, maxMarkers]); // eslint-disable-line

  const legendCats = [];

  return (
    <div className="w-full h-full relative">
      <div ref={mapRef} data-testid="map-container" className="w-full h-full" />
      {legendCats.length > 0 && false && (
        <div data-testid="map-legend"
          className="absolute bottom-6 left-3 z-[1000] bg-surface/90 backdrop-blur-md border border-line rounded-sm p-3 max-w-[210px]">
          <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500 mb-1.5">{t("legend")}</p>
          {legendCats.map((c) => (
            <div key={c.name} className="flex items-center gap-2 py-0.5">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: c.color, boxShadow: `0 0 6px ${c.color}66` }} />
              <span className="text-[11px] text-slate-300 truncate">{t("cat_" + c.name)}</span>
              <span className="font-mono text-[9px] text-slate-500 ml-auto">{c.count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
