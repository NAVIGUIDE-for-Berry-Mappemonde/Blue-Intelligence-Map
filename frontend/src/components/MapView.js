import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet.markercluster";
import api from "../api";

const TILE_URLS = {
  dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  light: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
};

const FALLBACK_COLORS = {
  "MPA": "#00f0ff", "Conservation": "#39ff14", "Research": "#c084fc",
  "Fisheries": "#fbbf24", "Policy & Advocacy": "#f472b6", "Pollution": "#ff4a4a",
  "Coastal & Habitat": "#34d399", "Education": "#60a5fa", "Other": "#94a3b8",
};

const LFP_COLORS = { 1: "#60a5fa", 2: "#34d399", 3: "#fbbf24", 4: "#ef4444", 5: "#a855f7", 0: "#94a3b8" };
const MPA_MIN_ZOOM = 5;

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
  formalities,
  territories,
  route,
  selectedTerritory,
  selectedEscale,
  onSelectEscale,
  flyToMarina,
  flyToEscale,
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
  const marinaMarkersById = useRef(new Map());
  const marinaSigRef = useRef("");
  const tileRef = useRef(null);
  const sigRef = useRef("");
  const zoomingRef = useRef(false);
  const pendingRef = useRef(null);
  const mpaLayerRef = useRef(null);
  const mpaOnRef = useRef(false);
  const mpaLoadingRef = useRef(false);
  const routeLayerRef = useRef(null);
  const routeLoadedRef = useRef(false);
  // Phase 4A — Formalities layer
  const formalitiesLayerRef = useRef(null);
  const formalitiesMarkersByEscale = useRef(new Map());
  const formalitiesSigRef = useRef("");
  const [mpaOn, setMpaOn] = useState(false);
  const [mpaZoomHint, setMpaZoomHint] = useState(false);
  const [routeOn, setRouteOn] = useState(true);
  const [lfpFilter, setLfpFilter] = useState({ 1: true, 2: true, 3: true, 4: true, 5: true });
  const lfpFilterRef = useRef(lfpFilter);
  const mpaDataRef = useRef(null);

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
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: "abcd",
      maxZoom: 19,
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
    // Add whichever cluster matches the initial mode; the mode-swap effect will fix it up
    // if the user is starting in another mode. In "formalities" mode neither cluster is
    // attached — only the route + the escale-status layer show.
    if (mode === "marinas") map.addLayer(marinaCluster);
    else if (mode !== "formalities") map.addLayer(cluster);
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
    // ProtectedSeas MPA overlay
    const mpaLayer = L.geoJSON(null, {
      style: (f) => ({
        color: LFP_COLORS[f.properties.lfp] || LFP_COLORS[0],
        weight: 1.6,
        fillColor: LFP_COLORS[f.properties.lfp] || LFP_COLORS[0],
        fillOpacity: 0.28,
      }),
      onEachFeature: (f, layer) => {
        const p = f.properties;
        const col = LFP_COLORS[p.lfp] || LFP_COLORS[0];
        layer.bindPopup(`
          <div style="min-width:220px;max-width:270px;">
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${p.site_name || "MPA"}</div>
            <div style="margin:5px 0;"><span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:${col};border:1px solid ${col}66;padding:2px 6px;border-radius:2px;">LFP ${p.lfp || "?"} — ${t("lfp" + (p.lfp || 0))}</span></div>
            <div style="font-size:11px;color:#94a3b8;line-height:1.5;">
              ${p.designation ? p.designation + "<br/>" : ""}${p.country || ""}${p.managing_authority ? " · " + p.managing_authority : ""}
            </div>
            ${p.url ? `<a href="${p.url}" target="_blank" rel="noreferrer" style="font-size:11px;color:#00f0ff;font-weight:600;text-decoration:none;">${t("viewProject")} →</a>` : ""}
            <div style="font-size:9px;color:#64748b;margin-top:6px;line-height:1.4;">${t("mpaDisclaimer")}<br/>ProtectedSeas Navigator® — CC BY 4.0</div>
          </div>
        `, { maxWidth: 280, autoPan: false });
      },
    });
    mpaLayerRef.current = mpaLayer;
    const renderMpa = () => {
      const data = mpaDataRef.current;
      mpaLayer.clearLayers();
      if (!data) return;
      const flt = lfpFilterRef.current;
      mpaLayer.addData({
        ...data,
        features: (data.features || []).filter((f) => {
          const s = f.properties.lfp;
          return s >= 1 && s <= 5 ? flt[s] : true;
        }),
      });
    };
    map.__renderMpa = renderMpa;
    const loadMpa = async () => {
      if (!mpaOnRef.current || mpaLoadingRef.current) return;
      if (map.getZoom() < MPA_MIN_ZOOM) {
        setMpaZoomHint(true);
        mpaDataRef.current = null;
        mpaLayer.clearLayers();
        return;
      }
      setMpaZoomHint(false);
      mpaLoadingRef.current = true;
      try {
        const b = map.getBounds();
        const bbox = `${b.getWest().toFixed(3)},${b.getSouth().toFixed(3)},${b.getEast().toFixed(3)},${b.getNorth().toFixed(3)}`;
        const { data } = await api.get(`/mpa?bbox=${bbox}`, { timeout: 120000 });
        mpaDataRef.current = data;
        renderMpa();
      } catch (e) { /* transient */ } finally {
        mpaLoadingRef.current = false;
      }
    };
    map.on("moveend", loadMpa);
    map.__loadMpa = loadMpa;
    mapObj.current = map;
    clusterRef.current = cluster;
  }, [minZoom]);

  useEffect(() => {
    lfpFilterRef.current = lfpFilter;
    if (mapObj.current && mapObj.current.__renderMpa && mpaOnRef.current) mapObj.current.__renderMpa();
  }, [lfpFilter]);

  useEffect(() => {
    const map = mapObj.current;
    const layer = mpaLayerRef.current;
    if (!map || !layer) return;
    mpaOnRef.current = mpaOn;
    if (mpaOn) {
      map.addLayer(layer);
      map.attributionControl.addAttribution("ProtectedSeas Navigator® CC BY 4.0");
      map.__loadMpa();
    } else {
      mpaDataRef.current = null;
      layer.clearLayers();
      map.removeLayer(layer);
      map.attributionControl.removeAttribution("ProtectedSeas Navigator® CC BY 4.0");
      setMpaZoomHint(false);
    }
  }, [mpaOn]);

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
          // dark casing for contrast on light basemap
          L.polyline(latlngs, {
            color: ROUTE_CASING_COLOR,
            weight: ROUTE_CASING_WEIGHT,
            opacity: 0.35,
            lineCap: "round",
            lineJoin: "round",
            interactive: false,
          }).addTo(group);
          // main stroke on top
          const main = L.polyline(latlngs, {
            color: ROUTE_MAIN_COLOR,
            weight: ROUTE_MAIN_WEIGHT,
            opacity: 0.95,
            dashArray: isOverland ? "6 6" : null,
            lineCap: "round",
            lineJoin: "round",
          });
          main.bindTooltip(
            `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;">${
              isOverland ? t("routeSegmentOverland") : t("routeSegmentMaritime")
            }</span><br/><span style="font-size:10px;color:#cbd5e1;">${p.from || ""} → ${p.to || ""}</span>`,
            { sticky: true, className: "bi-route-tt", direction: "top", opacity: 0.95 },
          );
          main.addTo(group);
        } else if (g.type === "Point") {
          const [lng, lat] = g.coordinates;
          const isEscale = p.point_type === "escale";
          if (isEscale) escales.push({ lat, lng, name: p.name });
          else intermediates.push({ lat, lng, name: p.name });
        }
      });
      // Intermediate waypoints — small muted dots, hover tooltip only
      intermediates.forEach((w) => {
        const m = L.circleMarker([w.lat, w.lng], {
          radius: 2.5,
          color: INTERMEDIATE_STROKE,
          weight: 1,
          fillColor: INTERMEDIATE_FILL,
          fillOpacity: 0.9,
        });
        m.bindTooltip(
          `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#cbd5e1;">${t(
            "routeWaypointIntermediate",
          )}</span><br/><span style="font-size:10px;">${w.name || ""}</span>`,
          { direction: "top", className: "bi-route-tt", opacity: 0.95 },
        );
        m.bindPopup(
          `<div style="min-width:180px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.1em;">${t(
              "routeWaypointIntermediate",
            )}</div>
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:13px;color:#fff;line-height:1.3;margin-top:4px;">${
              w.name || ""
            }</div>
          </div>`,
          { maxWidth: 240, autoPan: false },
        );
        m.addTo(group);
      });
      // Escale waypoints — larger, permanent labels below the dot
      escales.forEach((w) => {
        const m = L.circleMarker([w.lat, w.lng], {
          radius: 6,
          color: ESCALE_STROKE,
          weight: 2,
          fillColor: ESCALE_FILL,
          fillOpacity: 1,
        });
        m.bindTooltip(w.name || "", {
          direction: "bottom",
          offset: [0, 6],
          permanent: true,
          className: "bi-route-escale-label",
        });
        m.bindPopup(
          `<div style="min-width:200px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#00f0ff;text-transform:uppercase;letter-spacing:0.1em;">${t(
              "routeWaypointEscale",
            )}</div>
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;margin-top:4px;">${
              w.name || ""
            }</div>
            <div style="font-size:9px;color:#64748b;margin-top:6px;line-height:1.4;">${t("routeAttribution")}</div>
          </div>`,
          { maxWidth: 260, autoPan: false },
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
      // Priority label localised via t()
      const prioLabels = { 1: t("marinasPriority1"), 2: t("marinasPriority2"), 3: t("marinasPriority3") };
      const srcLabels = {
        openstreetmap: t("marinasSourceOSM"),
        shom: t("marinasSourceSHOM"),
        curated: t("marinasSourceCurated"),
      };
      // Tag rows (only render those present)
      const tagRow = (label, value, isLink = false) => {
        if (!value) return "";
        const disp = isLink
          ? `<a href="${value}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;">${value.replace(/^https?:\/\//, "").slice(0, 40)}</a>`
          : String(value);
        return `<div style="font-size:11px;color:#94a3b8;margin-top:3px;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${label}</span> ${disp}</div>`;
      };
      const vhf = tags.vhf_channel || tags.vhf;
      const phone = tags.phone || tags["contact:phone"];
      const website = tags.website || tags["contact:website"] || tags.url;
      const capacity = tags.capacity || tags["capacity:persons"] || tags["seamark:harbour:capacity"];
      const depth = tags.max_depth || tags.depth || tags["seamark:harbour:draught"];
      const fee = tags.fee;

      // Enrichment block — visible when the marina has been enriched (source: tinyfish/openrouter/fallback)
      const enrSource = p.enrichment_source;
      const enrSourceLabel = {
        tinyfish: t("enrichSourceTinyfish"),
        openrouter: t("enrichSourceOpenrouter"),
        fallback: t("enrichSourceFallback"),
      }[enrSource] || "";
      const stars = (n) => (n && n >= 1 && n <= 5) ? "★".repeat(n) + "☆".repeat(5 - n) : null;
      const enrichRow = (label, value) => {
        if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) return "";
        const disp = Array.isArray(value)
          ? value.map((v) => `<span style="display:inline-block;background:rgba(255,74,74,0.10);border:1px solid rgba(255,74,74,0.35);color:#fecaca;font-size:9px;font-family:'JetBrains Mono',monospace;padding:1px 5px;border-radius:2px;margin:1px 3px 1px 0;">${String(v)}</span>`).join("")
          : String(value);
        return `<div style="font-size:11px;color:#e2e8f0;margin-top:5px;line-height:1.35;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;display:block;margin-bottom:1px;">${label}</span>${disp}</div>`;
      };
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

      m.bindPopup(
        `<div style="min-width:240px;max-width:300px;">
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
        </div>`,
        { maxWidth: 320, autoPan: false },
      );
      marinaMarkersById.current.set(p.id, m);
      return m;
    });
    marinaCluster.addLayers(markers);
  }, [marinas, t]);

  // ---------- Mode swap: attach the right cluster, hide the others (Phase 4A: 3 modes) ----------
  useEffect(() => {
    const map = mapObj.current;
    const proj = clusterRef.current;
    const mar = marinaClusterRef.current;
    const form = formalitiesLayerRef.current;
    if (!map || !proj || !mar) return;
    // Detach everything first, then attach only the layer for the current mode.
    if (map.hasLayer(proj)) map.removeLayer(proj);
    if (map.hasLayer(mar)) map.removeLayer(mar);
    if (form && map.hasLayer(form)) map.removeLayer(form);
    if (mode === "marinas") {
      map.addLayer(mar);
    } else if (mode === "formalities") {
      if (form) map.addLayer(form);
    } else {
      map.addLayer(proj);
    }
    map.closePopup();
  }, [mode]);

  // ---------- FlyTo signal from MarinasPanel ----------
  useEffect(() => {
    if (!flyToMarina) return;
    const map = mapObj.current;
    if (!map) return;
    const m = marinaMarkersById.current.get(flyToMarina.id);
    map.flyTo([flyToMarina.lat, flyToMarina.lon], Math.max(map.getZoom(), 10), { duration: 1.0 });
    setTimeout(() => { if (m) m.openPopup(); }, 1100);
  }, [flyToMarina]);

  // ---------- Phase 4A — Formalities layer: escales coloured by status +
  // white ring on ports of entry. Only rebuilt when the underlying data
  // signature (routes / formalities status / territory mapping) changes.
  useEffect(() => {
    const map = mapObj.current;
    if (!map) return;
    if (!route?.features?.length || !territories?.territories?.length) {
      // No data yet — bail out but do not tear down anything.
      return;
    }

    // Colour tokens for escale status
    const STATUS_FILL = {
      non_generee:     "#64748b",   // slate-500
      ia:              "#fbbf24",   // amberx solid
      ia_sans_source:  "#fbbf24",   // amberx dashed (see stroke below)
      verifiee:        "#39ff14",   // bio-green
    };
    const STATUS_STROKE = {
      non_generee:     "#334155",
      ia:              "#0f172a",
      ia_sans_source:  "#fbbf24",
      verifiee:        "#0f172a",
    };

    // territory lookup by escale name
    const escaleToTerritory = {};
    for (const terr of territories.territories) {
      for (const en of terr.escale_names || []) {
        escaleToTerritory[en] = terr;
      }
    }
    // formalities by territory code
    const forByCode = {};
    for (const f of formalities || []) forByCode[f.territory_code] = f;

    // Collect all escale features
    const escaleFeats = route.features.filter(
      (f) => f.geometry?.type === "Point" && f.properties?.point_type === "escale",
    );
    // Signature for skip-rebuild
    const statusSig = escaleFeats.map((f) => {
      const name = f.properties.name;
      const terr = escaleToTerritory[name];
      const forDoc = terr ? forByCode[terr.code] : null;
      return `${name}|${terr?.code || ""}|${forDoc?.status || "none"}`;
    }).join(";");
    if (statusSig === formalitiesSigRef.current && formalitiesLayerRef.current) return;
    formalitiesSigRef.current = statusSig;

    // (Re)build the layer
    if (formalitiesLayerRef.current && map.hasLayer(formalitiesLayerRef.current)) {
      map.removeLayer(formalitiesLayerRef.current);
    }
    const layer = L.layerGroup();
    formalitiesMarkersByEscale.current.clear();

    // La Rochelle appears twice in the route; tag them départ/retour by order.
    const laRochelleSeen = { count: 0 };
    escaleFeats.forEach((feat) => {
      const [lon, lat] = feat.geometry.coordinates;
      const name = feat.properties.name;
      const terr = escaleToTerritory[name];
      const forDoc = terr ? forByCode[terr.code] : null;
      const status = forDoc?.status || "non_generee";
      const overlay = forDoc?.escale_overlays?.find((o) => o.escale_name === name);
      const isPoe = !!overlay?.is_port_of_entry;
      const dashed = status === "ia_sans_source";
      const fill = STATUS_FILL[status] || STATUS_FILL.non_generee;
      const stroke = STATUS_STROKE[status] || STATUS_STROKE.non_generee;

      // Ring badge (port of entry) — drawn UNDER the marker
      if (isPoe) {
        const ring = L.circleMarker([lat, lon], {
          radius: 11,
          fill: false,
          color: "#f8fafc",
          weight: 2,
          opacity: 0.95,
          className: "bi-poe-ring",
          interactive: false,
        });
        layer.addLayer(ring);
      }

      let leg = null;
      if (name === "La Rochelle") {
        laRochelleSeen.count += 1;
        leg = laRochelleSeen.count === 1 ? "departure" : "return";
      }

      const marker = L.circleMarker([lat, lon], {
        radius: 7,
        color: stroke,
        weight: dashed ? 2 : 1.5,
        fillColor: fill,
        fillOpacity: 0.9,
        className: dashed ? "bi-escale-marker--dashed" : "",
      });

      const statusLabel = {
        non_generee: t("formalitiesStatusNonGeneree"),
        ia: t("formalitiesStatusIa"),
        ia_sans_source: t("formalitiesStatusIaSansSource"),
        verifiee: t("formalitiesStatusVerifiee"),
      }[status];
      const poeLabel = isPoe ? t("formalitiesPortOfEntry") : t("formalitiesNotPortOfEntry");
      const legLabel = leg ? ` · ${leg === "departure" ? t("formalitiesLegDeparture") : t("formalitiesLegReturn")}` : "";
      const noteHtml = overlay?.note
        ? `<div style="font-size:11px;color:#94a3b8;margin-top:5px;line-height:1.4;">${overlay.note}</div>`
        : "";
      const flag = terr?.flag_emoji || "🏳️";

      marker.bindPopup(
        `<div style="min-width:220px;max-width:280px;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">
            ${flag} ${name}${legLabel}
          </div>
          <div style="font-size:11px;color:#94a3b8;margin:4px 0 6px;">${terr?.name_fr || ""}</div>
          <div style="margin:4px 0 6px;display:flex;flex-wrap:wrap;gap:4px;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${fill};border:1px solid ${fill}55;padding:2px 6px;border-radius:2px;">${statusLabel}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${isPoe ? "#f8fafc" : "#64748b"};border:1px solid ${isPoe ? "#f8fafc99" : "#33415555"};padding:2px 6px;border-radius:2px;">
              ${isPoe ? "⚓ " : ""}${poeLabel}
            </span>
          </div>
          ${noteHtml}
        </div>`,
        { maxWidth: 300, autoPan: false },
      );

      // Click on marker → open the corresponding territory card in the panel
      marker.on("click", () => {
        if (typeof onSelectEscale === "function" && terr?.code) {
          onSelectEscale(name, terr.code, [lon, lat]);
        }
      });

      layer.addLayer(marker);
      formalitiesMarkersByEscale.current.set(name + (leg ? `::${leg}` : ""), marker);
    });

    formalitiesLayerRef.current = layer;
    if (mode === "formalities") map.addLayer(layer);
  }, [route, territories, formalities, t, mode, onSelectEscale]);

  // ---------- FlyTo signal from FormalitiesPanel (escale row click) ----------
  useEffect(() => {
    if (!flyToEscale) return;
    const map = mapObj.current;
    if (!map) return;
    map.flyTo([flyToEscale.lat, flyToEscale.lon], Math.max(map.getZoom(), 6), { duration: 1.0 });
  }, [flyToEscale]);

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
        const snapped = p.snapped ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#fbbf24;border:1px solid #fbbf2455;padding:1px 5px;border-radius:2px;margin-left:6px;">${t("snappedBadge")}</span>` : "";
        const cat = p.category_group ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${col};border:1px solid ${col}55;padding:1px 5px;border-radius:2px;">${t("cat_" + p.category_group)}</span>` : "";
        marker.bindPopup(`
          <div style="min-width:220px;max-width:270px;">
            ${img}
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${p.title}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#c084fc;margin:4px 0;">${p.funder}${snapped}</div>
            <div style="margin:2px 0 6px;">${cat}</div>
            <div style="font-size:11px;color:#94a3b8;line-height:1.45;margin-bottom:6px;">${p.description || ""}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;gap:5px;flex-wrap:wrap;">
              <a href="${p.url}" target="_blank" rel="noreferrer" style="font-size:11px;color:#00f0ff;font-weight:600;text-decoration:none;">${t("viewProject")} →</a>
              <button onclick="window.__biDonate && window.__biDonate('${p.id}')" data-testid="popup-donate-btn" style="font-size:10px;font-weight:600;color:#39ff14;background:rgba(57,255,20,0.08);border:1px solid rgba(57,255,20,0.4);border-radius:2px;padding:2px 8px;cursor:pointer;">${t("donate")}</button>
              <button onclick="window.__biEnrichProject && window.__biEnrichProject('${p.id}')" data-testid="popup-project-enrich-btn" style="font-size:10px;font-weight:600;color:#00f0ff;background:rgba(0,240,255,0.08);border:1px solid rgba(0,240,255,0.4);border-radius:2px;padding:2px 8px;cursor:pointer;">↻ ${t("projectEnrich")}</button>
              ${p.s_ocean != null ? `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#39ff14;">S<sub>ocean</sub> ${p.s_ocean}</span>` : ""}
            </div>
          </div>
        `, { maxWidth: 280, autoPan: false });
        return marker;
      });
      cluster.addLayers(markers);
    };

    if (zoomingRef.current) {
      pendingRef.current = apply;
    } else {
      apply();
    }
  }, [projects, funderFilter, categoryFilter, searchQuery, maxMarkers, t]); // eslint-disable-line

  const legendCats = [];

  return (
    <div className="w-full h-full relative">
      <div ref={mapRef} data-testid="map-container" className="w-full h-full" />
      {/* ProtectedSeas layer toggle */}
      <div className="absolute top-3 right-3 z-[1000] flex flex-col items-end gap-2">
        <button data-testid="route-toggle-btn" onClick={() => setRouteOn(!routeOn)}
          className={`px-3 py-2 text-xs font-semibold border rounded-sm backdrop-blur-md ${routeOn ? "bg-slate-100/10 border-slate-300/50 text-slate-100" : "bg-surface/90 border-line text-slate-400 hover:text-white"}`}>
          ⛵ {t("routeLayer")}
        </button>
        <button data-testid="mpa-toggle-btn" onClick={() => setMpaOn(!mpaOn)}
          className={`px-3 py-2 text-xs font-semibold border rounded-sm backdrop-blur-md ${mpaOn ? "bg-sonar/20 border-sonar/60 text-sonar" : "bg-surface/90 border-line text-slate-300 hover:text-white"}`}>
          🛡 {t("mpaLayer")}
        </button>
        {mpaOn && mpaZoomHint && (
          <span data-testid="mpa-zoom-hint" className="px-2 py-1 text-[10px] font-mono bg-surface/90 border border-line rounded-sm text-amberx">{t("mpaZoomHint")}</span>
        )}
        {mpaOn && !mpaZoomHint && (
          <div data-testid="mpa-legend" className="bg-surface/90 backdrop-blur-md border border-line rounded-sm p-2 text-right">
            {[1, 2, 3, 4, 5].map((s) => (
              <label key={s} data-testid={`lfp-checkbox-row-${s}`} className="flex items-center justify-end gap-1.5 py-0.5 cursor-pointer select-none hover:bg-raised/60 rounded-sm px-1">
                <span className={`text-[10px] ${lfpFilter[s] ? "text-slate-300" : "text-slate-600 line-through"}`}>LFP {s} — {t("lfp" + s)}</span>
                <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: LFP_COLORS[s], opacity: lfpFilter[s] ? 1 : 0.25 }} />
                <input type="checkbox" data-testid={`lfp-checkbox-${s}`} checked={lfpFilter[s]}
                  onChange={(e) => setLfpFilter({ ...lfpFilter, [s]: e.target.checked })}
                  className="accent-cyan-400 w-3 h-3" />
              </label>
            ))}
            <p className="text-[8px] text-slate-500 mt-1 max-w-[190px]">{t("mpaDisclaimer")}</p>
          </div>
        )}
      </div>
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
