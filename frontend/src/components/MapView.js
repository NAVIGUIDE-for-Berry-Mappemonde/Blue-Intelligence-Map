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

// Phase 5 — MPA layer removed. LFP_COLORS/MPA_MIN_ZOOM constants deleted;
// see /api/mpa endpoint removal + mpa_cache collection drop.

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
  const formalitiesClusterRef = useRef(null);
  const marinaMarkersById = useRef(new Map());
  const marinaSigRef = useRef("");
  const tileRef = useRef(null);
  const sigRef = useRef("");
  const zoomingRef = useRef(false);
  const pendingRef = useRef(null);
  const routeLayerRef = useRef(null);
  const routeLoadedRef = useRef(false);
  // Phase 4A — Formalities layer
  // Phase 7 — formalitiesLayerRef removed: markers now live inside the shared
  // formalitiesClusterRef (leaflet.markercluster) for unified rendering.
  const formalitiesMarkersByEscale = useRef(new Map());
  const formalitiesSigRef = useRef("");
  const [routeOn] = useState(true);

  // Phase 7bis — Popup content must reflect the CURRENT language, not the one
  // captured when markers were bound. We keep `t` and formality data in refs
  // refreshed every render, then let bindPopup(fn) read them at open time.
  const tRef = useRef(t);
  tRef.current = t;
  const formalitiesRef = useRef(formalities);
  formalitiesRef.current = formalities;
  const territoriesRef = useRef(territories);
  territoriesRef.current = territories;
  // Popup-open bug fix (2026-08-24): keep the selection callback in a ref so
  // the formalities markers rebuild effect does NOT depend on it. Even when
  // App.js already wraps handleSelectEscale in useCallback([]), we want the
  // effect deps to advertise "data only" and never re-fire on selection.
  const onSelectEscaleRef = useRef(onSelectEscale);
  onSelectEscaleRef.current = onSelectEscale;

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
    // Phase 7 — Formalities layer (amber).
    //
    // SPM disappearance bug-fix (2026-08-24): we USED to wrap this layer in
    // `L.markerClusterGroup` but its post-init "in-bounds" cache is stubbornly
    // wrong for markers that fall outside the initial map viewport
    // (Saint-Pierre-et-Miquelon at lng=-56, Papeete at lng=-149, Nouméa at
    // lng=+166, Wallis at lng=-176 all ended up with __parent still pointing
    // at the ROOT cluster at zoom 1 with hasIcon=false — they never got a
    // DOM element even with removeOutsideVisibleBounds=false AND
    // disableClusteringAtZoom=4). With only 17 escale markers in this layer,
    // clustering is aesthetic-only, so we drop it entirely: a plain
    // `L.featureGroup` guarantees every marker gets a DOM element the moment
    // the layer is attached to the map. Popup open now Just Works for every
    // escale regardless of its longitude.
    //
    // NB: the ref is still called `formalitiesClusterRef` to keep the rest of
    // the codebase (flyToEscale effect, mode-swap effect) untouched. The
    // duck-typed methods we call on it (`clearLayers`, `addLayer`,
    // `getLayers`, `hasLayer`) are shared between `L.markerClusterGroup` and
    // `L.featureGroup`; the ones we don't call anymore (`zoomToShowLayer`,
    // `refreshClusters`) are guarded elsewhere with `typeof … === "function"`.
    const formalitiesCluster = L.featureGroup();
    formalitiesClusterRef.current = formalitiesCluster;
    // Add whichever cluster matches the initial mode; the mode-swap effect will fix it up
    // if the user is starting in another mode.
    if (mode === "marinas") map.addLayer(marinaCluster);
    else if (mode === "formalities") map.addLayer(formalitiesCluster);
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
      window.__biDebug = { map, projects: cluster, marinas: marinaCluster, formalities: formalitiesCluster };
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
          { maxWidth: 260, autoPan: true, keepInView: true, autoPanPadding: [40, 40] },
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
        { maxWidth: 320, maxHeight: 400, autoPan: true, keepInView: true, autoPanPadding: [40, 40] },
      );
      marinaMarkersById.current.set(p.id, m);
      return m;
    });
    marinaCluster.addLayers(markers);
  }, [marinas]);

  // ---------- Mode swap: attach the right cluster, hide the others (Phase 4A → Phase 7) ----------
  useEffect(() => {
    const map = mapObj.current;
    const proj = clusterRef.current;
    const mar = marinaClusterRef.current;
    const formCluster = formalitiesClusterRef.current;
    if (!map || !proj || !mar || !formCluster) return;
    // Detach everything first, then attach only the layer for the current mode.
    if (map.hasLayer(proj)) map.removeLayer(proj);
    if (map.hasLayer(mar)) map.removeLayer(mar);
    if (map.hasLayer(formCluster)) map.removeLayer(formCluster);
    if (mode === "marinas") {
      map.addLayer(mar);
    } else if (mode === "formalities") {
      map.addLayer(formCluster);
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

  // ---------- Phase 4A → Phase 6 — Formalities layer.
  // Escales coloured by status + white ring on ports of entry, unified with
  // Projects/Marinas circleMarker style (radius 7, weight 2, fillOpacity 0.6).
  // The popup now embeds the FULL fiche (entrée, sortie, cas particuliers,
  // immigration FR, contacts, liens officiels, sources) with refresh + verify
  // buttons — Phase 6 migration from the sidebar.
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
      non_generee:     "#0b1220",
      ia:              "#0b1220",
      ia_sans_source:  "#fbbf24",
      verifiee:        "#0b1220",
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
    // Signature for skip-rebuild — Phase 6 also includes stale/verified_at so the
    // popup body refreshes when the fiche is regenerated or verified.
    const statusSig = escaleFeats.map((f) => {
      const name = f.properties.name;
      const terr = escaleToTerritory[name];
      const forDoc = terr ? forByCode[terr.code] : null;
      return `${name}|${terr?.code || ""}|${forDoc?.status || "none"}|${forDoc?.generated_at || ""}|${forDoc?.verified_at || ""}|${forDoc?.stale ? "1" : "0"}`;
    }).join(";");
    if (statusSig === formalitiesSigRef.current && formalitiesClusterRef.current?.getLayers()?.length) return;
    formalitiesSigRef.current = statusSig;

    // Phase 7 — rebuild by clearing the shared formalities cluster (no more
    // per-effect layerGroup). This unifies rendering with projects/marinas
    // and gives us leaflet.markercluster grouping at world zoom.
    const cluster = formalitiesClusterRef.current;
    if (!cluster) return;
    cluster.clearLayers();
    formalitiesMarkersByEscale.current.clear();

    // ---- Field ordering — mirrors the pre-Phase-6 sidebar tabs ----
    const ENTREE_FIELDS = [
      ["preavis",              "formalitiesFieldsPreavis"],
      ["pavillon_q",           "formalitiesFieldsPavillonQ"],
      ["demarches_arrivee",    "formalitiesFieldsDemarchesArrivee"],
      ["ou_s_amarrer",         "formalitiesFieldsOuSAmarrer"],
      ["vhf",                  "formalitiesFieldsVhf"],
      ["douanes_clearance",    "formalitiesFieldsDouanesClearance"],
      ["admission_temporaire", "formalitiesFieldsAdmissionTemporaire"],
      ["franchises",           "formalitiesFieldsFranchises"],
      ["biosecurite",          "formalitiesFieldsBiosecurite"],
      ["frais",                "formalitiesFieldsFrais"],
      ["horaires",             "formalitiesFieldsHoraires"],
    ];
    const SORTIE_FIELDS = [
      ["clearance",   "formalitiesFieldsClearance"],
      ["delais",      "formalitiesFieldsDelais"],
      ["documents",   "formalitiesFieldsDocuments"],
      ["ou_obtenir",  "formalitiesFieldsOuObtenir"],
    ];
    const CAS_FIELDS = [
      ["animaux", "formalitiesFieldsAnimaux"],
      ["drones",  "formalitiesFieldsDrones"],
      ["armes",   "formalitiesFieldsArmes"],
    ];
    const IMMI_FIELDS = [
      ["visa",             "formalitiesFieldsVisa"],
      ["duree_sejour",     "formalitiesFieldsDureeSejour"],
      ["equivalent_esta",  "formalitiesFieldsEsta"],
      ["notes",            "formalitiesFieldsNotes"],
    ];

    // ---- Small HTML builders (inline styles keep popup self-contained) ----
    // i18n lazy-binding fix (2026-08-24): each helper reads `tRef.current` at
    // CALL time (not effect-run time), so section titles AND field labels all
    // reflect the CURRENT UI language when the popup is opened or refreshed.
    const esc = (s) => {
      if (s === null || s === undefined) return "";
      return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    };
    const groupHtml = (title, source, fields) => {
      if (!source) return "";
      const t = tRef.current;
      const rows = fields
        .filter(([k]) => source[k] !== null && source[k] !== undefined && source[k] !== "")
        .map(([k, labelKey]) => `
          <div style="margin-top:6px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:1px;">${esc(t(labelKey))}</div>
            <div style="font-size:11px;color:#e2e8f0;line-height:1.5;">${esc(source[k])}</div>
          </div>`)
        .join("");
      if (!rows) return "";
      return `
        <div style="margin-top:10px;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${esc(title)}</div>
          ${rows}
        </div>`;
    };
    const contactsHtml = (contacts, links) => {
      const t = tRef.current;
      const cItems = (contacts || []).map((c) => `
        <div style="font-size:11px;color:#e2e8f0;margin-top:4px;">
          <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;text-transform:uppercase;margin-right:6px;">${esc(c.type || "")}</span>
          ${esc(c.label || "")}: <span style="color:#fff;">${esc(c.value || "")}</span>
        </div>`).join("");
      const lItems = (links || []).map((l) => `
        <div style="margin-top:4px;"><a href="${esc(l.url)}" target="_blank" rel="noreferrer" style="font-size:11px;color:#00f0ff;text-decoration:none;">${esc(l.label || l.url)} →</a></div>`).join("");
      if (!cItems && !lItems) return "";
      return `
        <div style="margin-top:10px;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${esc(t("formalitiesPopupContactsTitle"))}</div>
          ${cItems}
          ${lItems ? `<div style="margin-top:6px;font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("formalitiesPopupLinksTitle"))}</div>${lItems}` : ""}
        </div>`;
    };
    const sourcesHtml = (sources, status) => {
      const t = tRef.current;
      const isNoSource = status === "ia_sans_source";
      const warn = isNoSource
        ? `<div style="margin-top:6px;padding:4px 6px;background:rgba(255,74,74,0.08);border:1px solid rgba(255,74,74,0.35);color:#fecaca;font-size:10px;line-height:1.4;border-radius:2px;">⚠️ ${esc(t("formalitiesNoSourceWarning"))}</div>`
        : "";
      if (!sources || sources.length === 0) {
        return `
          <div style="margin-top:10px;">
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${esc(t("formalitiesPopupSourcesTitle"))}</div>
            ${warn}
            <div style="margin-top:4px;font-size:11px;color:#94a3b8;font-style:italic;">${esc(t("formalitiesNoSourceEmpty"))}</div>
          </div>`;
      }
      const items = sources.map((s) => `
        <div style="margin-top:4px;font-size:11px;line-height:1.4;">
          <a href="${esc(s.url)}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;word-break:break-all;">${esc(s.url)}</a>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;margin-top:1px;">
            ${esc(s.domain || "")}${s.collected_at ? " · " + esc(String(s.collected_at).slice(0, 10)) : ""}
          </div>
        </div>`).join("");
      return `
        <div style="margin-top:10px;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:600;font-size:11px;color:#fbbf24;text-transform:uppercase;letter-spacing:0.08em;border-bottom:1px solid rgba(251,191,36,0.25);padding-bottom:2px;">${esc(t("formalitiesPopupSourcesTitle"))}</div>
          ${warn}
          ${items}
        </div>`;
    };

    // ---- Popup HTML builder for a full territory fiche.
    //      Phase 7bis — reads `t` from tRef.current so popups always reflect
    //      the current UI language even if built earlier.                  ----
    const buildPopup = (feat, meta) => {
      const t = tRef.current;                                    // lazy read
      const {
        name, leg, terr, forDoc, isPoe, status, fill, overlay,
      } = meta;
      const statusLabel = {
        non_generee: t("formalitiesStatusNonGeneree"),
        ia: t("formalitiesStatusIa"),
        ia_sans_source: t("formalitiesStatusIaSansSource"),
        verifiee: t("formalitiesStatusVerifiee"),
      }[status];
      const poeLabel = isPoe ? t("formalitiesPortOfEntry") : t("formalitiesNotPortOfEntry");
      const legLabel = leg
        ? ` · ${leg === "departure" ? t("formalitiesLegDeparture") : t("formalitiesLegReturn")}`
        : "";
      const noteHtml = overlay?.note
        ? `<div style="font-size:11px;color:#94a3b8;margin-top:5px;line-height:1.4;">${esc(overlay.note)}</div>`
        : "";
      const flag = terr?.flag_emoji || "🏳️";
      const genDate = forDoc?.generated_at ? String(forDoc.generated_at).slice(0, 10) : null;
      const verDate = forDoc?.verified_at ? String(forDoc.verified_at).slice(0, 10) : null;
      const staleBadge = forDoc?.stale
        ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#fbbf24;border:1px solid rgba(251,191,36,0.5);background:rgba(251,191,36,0.1);padding:2px 6px;border-radius:2px;">⏰ ${esc(t("formalitiesStale"))}</span>`
        : "";

      // Refresh + verify buttons (only when a territory code exists)
      const code = terr?.code || "";
      const canVerify = status === "ia" || status === "ia_sans_source";
      const refreshBtn = code
        ? `<button
            data-testid="formalities-refresh-btn"
            onclick="window.__biFormalityPopupRefresh && window.__biFormalityPopupRefresh('${esc(code)}')"
            style="font-size:10px;font-weight:600;color:#fbbf24;background:rgba(251,191,36,0.10);border:1px solid rgba(251,191,36,0.45);border-radius:2px;padding:3px 10px;cursor:pointer;">
            ↻ ${esc(t("formalitiesRefreshBtn"))}
          </button>`
        : "";
      const verifyBtn = code && canVerify
        ? `<button
            data-testid="formalities-verify-btn"
            onclick="window.__biFormalityPopupVerify && window.__biFormalityPopupVerify('${esc(code)}')"
            style="font-size:10px;font-weight:600;color:#39ff14;background:rgba(57,255,20,0.10);border:1px solid rgba(57,255,20,0.45);border-radius:2px;padding:3px 10px;cursor:pointer;">
            ✓ ${esc(t("formalitiesVerifyBtn"))}
          </button>`
        : "";

      // Body — either "not generated" hint OR all sections
      let body = "";
      if (!forDoc || status === "non_generee") {
        body = `<div style="margin-top:10px;padding:8px;background:rgba(100,116,139,0.10);border:1px solid rgba(100,116,139,0.30);color:#94a3b8;font-size:11px;line-height:1.5;border-radius:2px;">${esc(t("formalitiesPopupNotGenerated"))}</div>`;
      } else {
        const entree = groupHtml(t("formalitiesPopupEntreeTitle"), forDoc.entree, ENTREE_FIELDS);
        const sortie = groupHtml(t("formalitiesPopupSortieTitle"), forDoc.sortie, SORTIE_FIELDS);
        const cas = groupHtml(t("formalitiesPopupCasTitle"), forDoc.cas_particuliers, CAS_FIELDS);
        const immiSlot = (forDoc.immigration || {}).fr;
        const immi = immiSlot ? groupHtml(t("formalitiesPopupImmigrationTitle"), immiSlot, IMMI_FIELDS) : "";
        const contacts = contactsHtml(forDoc.contacts, forDoc.liens_officiels);
        const sources = sourcesHtml(forDoc.sources, status);
        body = entree + sortie + cas + immi + contacts + sources;
        if (!body) {
          body = `<div style="margin-top:10px;font-size:11px;color:#94a3b8;font-style:italic;">${esc(t("formalitiesPopupNoSectionData"))}</div>`;
        }
      }

      return `
        <div style="min-width:280px;max-width:340px;font-family:Manrope,sans-serif;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;">
            ${flag} ${esc(name)}${legLabel}
          </div>
          <div style="font-size:11px;color:#94a3b8;margin:4px 0 6px;">${esc(terr?.name_fr || "")}</div>
          <div style="margin:4px 0 6px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${fill};border:1px solid ${fill}55;padding:2px 6px;border-radius:2px;">${esc(statusLabel)}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${isPoe ? "#f8fafc" : "#64748b"};border:1px solid ${isPoe ? "#f8fafc99" : "#33415555"};padding:2px 6px;border-radius:2px;">${isPoe ? "⚓ " : ""}${esc(poeLabel)}</span>
            ${staleBadge}
          </div>
          ${genDate ? `<div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;">${esc(t("formalitiesGeneratedAt"))}: ${esc(genDate)}${verDate ? ` · <span style=\"color:#39ff14;\">${esc(t("formalitiesVerifiedAt"))}: ${esc(verDate)}</span>` : ""}</div>` : ""}
          ${(refreshBtn || verifyBtn)
            ? `<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">${refreshBtn}${verifyBtn}</div>`
            : ""}
          ${noteHtml}
          ${body}
        </div>`;
    };

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

      let leg = null;
      if (name === "La Rochelle") {
        laRochelleSeen.count += 1;
        leg = laRochelleSeen.count === 1 ? "departure" : "return";
      }

      // Phase 7bis — SINGLE self-contained div: iconSize matches exactly the
      // colored dot, no wrapper padding, no leaflet-div-icon default bg leak.
      // The .bi-status-icon class carries a defensive reset in index.css.
      const iconHtml = `<div style="width:14px;height:14px;border-radius:50%;background-color:${fill};border:1.5px ${dashed ? "dashed" : "solid"} ${stroke};box-sizing:border-box;"></div>`;
      const marker = L.marker([lat, lon], {
        icon: L.divIcon({
          html: iconHtml,
          className: "bi-status-icon",
          iconSize: [14, 14],
          iconAnchor: [7, 7],
          popupAnchor: [0, -7],
        }),
      });

      // Phase 7bis — bindPopup(FN) so the HTML is rebuilt at each open with
      // the CURRENT `t` (via tRef inside buildPopup). Fixes the FR↔EN closure
      // capture bug where popups kept the language captured at bind time.
      marker.bindPopup(
        () => buildPopup(feat, { name, leg, terr, forDoc, isPoe, status, fill, overlay }),
        // Popup overflow bug-fix 2026-08-24 — long fiches (Martinique with 8
        // ARRIVAL fields + 4 DEPARTURE + 3 SPECIAL + contacts + sources
        // easily exceeds 800 px) were rendered beyond the top of the map
        // container. `autoPan` pans the map so the popup fits, `keepInView`
        // clamps it inside the container, `maxHeight` caps at ~viewport and
        // Leaflet adds a native scrollbar inside the popup body.
        {
          maxWidth: 360,
          minWidth: 280,
          maxHeight: 400,
          autoPan: true,
          keepInView: true,
          autoPanPadding: [40, 40],
          className: "bi-formalities-popup",
        },
      );

      // Click on marker → tell App to fly there + tag the row in the sidebar.
      // Bug-fix 2026-08-24: read the handler from a ref so the rebuild effect
      // does NOT need to list onSelectEscale as a dep. Guarantees "data-only"
      // rebuild triggers.
      marker.on("click", () => {
        const cb = onSelectEscaleRef.current;
        if (typeof cb === "function" && terr?.code) {
          cb(name, terr.code, [lon, lat]);
        }
      });

      cluster.addLayer(marker);
      formalitiesMarkersByEscale.current.set(name + (leg ? `::${leg}` : ""), marker);
    });

    // Phase 7 — cluster is shared and attached by the mode-swap effect, no
    // per-render layerGroup to add.
    //
    // Popup-open bug fix (2026-08-24): deps are DATA-ONLY. `t`, `mode` and
    // `onSelectEscale` are intentionally excluded — `t` is read lazily via
    // `tRef.current` inside bindPopup(FN), `mode` doesn't affect marker
    // geometry (mode swap attaches/detaches the whole cluster in a separate
    // effect), and `onSelectEscale` is read via `onSelectEscaleRef.current`
    // inside the click handler. This guarantees a sidebar selection change
    // never triggers a marker rebuild.
  }, [route, territories, formalities]);

  // ---------- FlyTo signal from FormalitiesPanel (escale row click) ----------
  // Phase 7bis — deterministic chain: moveend → zoomToShowLayer → openPopup,
  // with a fallback fire('click') if openPopup didn't stick. No blind setTimeout.
  //
  // Popup-open bug fix (2026-08-24): `leaflet.markercluster.zoomToShowLayer`
  // silently does nothing when it enters the `panTo` branch and the map is
  // already at the destination (flyTo just landed there). In that case the
  // internal moveend never fires and the callback is never called. We now
  // detect a still-closed popup and, as a last resort, open the bound popup
  // directly on the map via `popup.setLatLng().openOn(map)` — this works
  // regardless of whether the marker's DOM icon has been attached yet.
  useEffect(() => {
    if (!flyToEscale) return;
    const map = mapObj.current;
    const cluster = formalitiesClusterRef.current;
    if (!map) return;

    let cancelled = false;

    const findTarget = () => {
      const markers = formalitiesMarkersByEscale.current;
      if (!markers || markers.size === 0) return null;
      if (flyToEscale.name && flyToEscale.leg) {
        const t = markers.get(`${flyToEscale.name}::${flyToEscale.leg}`);
        if (t) return t;
      }
      if (flyToEscale.name) {
        return markers.get(flyToEscale.name)
          || markers.get(`${flyToEscale.name}::departure`)
          || markers.get(`${flyToEscale.name}::return`)
          || null;
      }
      return null;
    };

    // Ultimate fallback: attach the marker's bound popup directly to the map
    // at its latlng. Works even when the marker's DOM icon hasn't been
    // attached yet by the cluster (the failing scenario for far-away escales).
    const forceOpenPopupOnMap = (target) => {
      if (!target || cancelled) return false;
      try {
        const popup = typeof target.getPopup === "function" ? target.getPopup() : null;
        if (popup && typeof popup.setLatLng === "function" && typeof popup.openOn === "function") {
          popup.setLatLng(target.getLatLng()).openOn(map);
          return true;
        }
      } catch (_) { /* noop */ }
      return false;
    };

    const openWithFallback = (target) => {
      if (!target || cancelled) return;
      // Attempt 1: standard openPopup (works when the marker has an _icon
      // attached in the DOM — the common case for close/visible escales).
      // openPopup() implicitly closes any currently-open popup first.
      try { target.openPopup(); } catch (_) { /* map or marker not ready */ }
      // Attempt 2: after a short delay, if the popup currently open is NOT
      // for our target (either because openPopup silently no-op'd on a marker
      // whose _icon hadn't been attached yet, OR because a different marker's
      // popup is still on the map), force-attach the target's own bound popup
      // directly to the map via `popup.setLatLng().openOn(map)`.
      //
      // Note: we check `map._popup._source === target` and NOT just "is there
      // any popup on the DOM". Otherwise clicking a sidebar row while another
      // popup is still open would let the previous popup persist (regression
      // detected 2026-08-24 during i18n test — clicking Papeete after opening
      // Martinique kept the Martinique popup on screen).
      //
      // We deliberately DO NOT `target.fire("click")` here — that would
      // re-trigger the sidebar's onSelectEscale handler, which re-sets
      // `flyToEscale`, which re-runs this whole effect, creating an infinite
      // loop for far-away escales whose _icon never gets attached.
      setTimeout(() => {
        if (cancelled) return;
        const currentPopup = map._popup;
        const isForTarget = !!(currentPopup && currentPopup._source === target);
        if (!isForTarget) forceOpenPopupOnMap(target);
      }, 250);
    };

    const doOpenTarget = () => {
      const target = findTarget();
      if (!target) return;
      if (cluster && typeof cluster.zoomToShowLayer === "function" && cluster.hasLayer(target)) {
        // `zoomToShowLayer` can silently no-op (see comment above). Guard with
        // a timeout that opens the popup directly if the callback never fires.
        let cbFired = false;
        cluster.zoomToShowLayer(target, () => {
          cbFired = true;
          openWithFallback(target);
        });
        setTimeout(() => {
          if (cancelled || cbFired) return;
          openWithFallback(target);
        }, 600);
      } else {
        openWithFallback(target);
      }
    };

    // Chain: fire flyTo → wait for moveend → open popup.
    // Fallback: if moveend never fires (already at destination), open after 900 ms.
    map.once("moveend", doOpenTarget);
    map.flyTo([flyToEscale.lat, flyToEscale.lon], Math.max(map.getZoom(), 6), { duration: 0.8 });
    const safety = setTimeout(doOpenTarget, 1500);

    return () => {
      cancelled = true;
      clearTimeout(safety);
      map.off("moveend", doOpenTarget);
    };
  }, [flyToEscale]);

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
        }, { maxWidth: 280, maxHeight: 400, autoPan: true, keepInView: true, autoPanPadding: [40, 40] });
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
