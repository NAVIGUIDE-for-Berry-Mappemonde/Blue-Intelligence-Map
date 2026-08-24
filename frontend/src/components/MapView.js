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
  const marinaMarkersById = useRef(new Map());
  const marinaSigRef = useRef("");
  const tileRef = useRef(null);
  const sigRef = useRef("");
  const zoomingRef = useRef(false);
  const pendingRef = useRef(null);
  const routeLayerRef = useRef(null);
  const routeLoadedRef = useRef(false);
  // Phase 4A — Formalities layer
  const formalitiesLayerRef = useRef(null);
  const formalitiesMarkersByEscale = useRef(new Map());
  const formalitiesSigRef = useRef("");
  const [routeOn] = useState(true);

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
    mapObj.current = map;
    clusterRef.current = cluster;
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
          `<div style="min-width:200px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:rgb(var(--accent-rgb));text-transform:uppercase;letter-spacing:0.1em;">${t(
              "routeWaypointEscale",
            )}</div>
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;margin-top:4px;">${
              w.name || ""
            }</div>
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
    // Signature for skip-rebuild — Phase 6 also includes stale/verified_at so the
    // popup body refreshes when the fiche is regenerated or verified.
    const statusSig = escaleFeats.map((f) => {
      const name = f.properties.name;
      const terr = escaleToTerritory[name];
      const forDoc = terr ? forByCode[terr.code] : null;
      return `${name}|${terr?.code || ""}|${forDoc?.status || "none"}|${forDoc?.generated_at || ""}|${forDoc?.verified_at || ""}|${forDoc?.stale ? "1" : "0"}`;
    }).join(";");
    if (statusSig === formalitiesSigRef.current && formalitiesLayerRef.current) return;
    formalitiesSigRef.current = statusSig;

    // (Re)build the layer
    if (formalitiesLayerRef.current && map.hasLayer(formalitiesLayerRef.current)) {
      map.removeLayer(formalitiesLayerRef.current);
    }
    const layer = L.layerGroup();
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
    const esc = (s) => {
      if (s === null || s === undefined) return "";
      return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    };
    const groupHtml = (title, source, fields) => {
      if (!source) return "";
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

    // ---- Popup HTML builder for a full territory fiche ----
    const buildPopup = (feat, meta) => {
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

      // Phase 6 — unified marker style with projects/marinas (radius 7, weight 2, fillOpacity 0.6)
      const marker = L.circleMarker([lat, lon], {
        radius: 7,
        color: stroke,
        weight: 2,
        fillColor: fill,
        fillOpacity: 0.6,
        className: dashed ? "bi-escale-marker--dashed" : "",
      });

      marker.bindPopup(
        buildPopup(feat, { name, leg, terr, forDoc, isPoe, status, fill, overlay }),
        { maxWidth: 360, minWidth: 280, autoPan: false, className: "bi-formalities-popup" },
      );

      // Click on marker → tell App to fly there + tag the row in the sidebar.
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
  // Phase 6 — also open the popup of the target escale so the fiche is visible
  // straight away (the fiche now lives inside the popup, not the sidebar).
  useEffect(() => {
    if (!flyToEscale) return;
    const map = mapObj.current;
    if (!map) return;
    map.flyTo([flyToEscale.lat, flyToEscale.lon], Math.max(map.getZoom(), 6), { duration: 1.0 });
    // Wait for the flyTo to end then open the marker's popup
    const openTimer = setTimeout(() => {
      const markers = formalitiesMarkersByEscale.current;
      if (!markers || markers.size === 0) return;
      // Look up: exact "name::leg" if leg is known, else just by name (first match wins)
      let target = null;
      if (flyToEscale.name && flyToEscale.leg) {
        target = markers.get(`${flyToEscale.name}::${flyToEscale.leg}`) || null;
      }
      if (!target && flyToEscale.name) {
        target = markers.get(flyToEscale.name)
          || markers.get(`${flyToEscale.name}::departure`)
          || markers.get(`${flyToEscale.name}::return`);
      }
      if (target && typeof target.openPopup === "function") target.openPopup();
    }, 1150);
    return () => clearTimeout(openTimer);
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
