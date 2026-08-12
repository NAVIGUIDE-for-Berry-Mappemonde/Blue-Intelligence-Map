import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet.markercluster";

const TILE_URLS = {
  dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  light: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
};

const FALLBACK_COLORS = {
  "MPA": "#00f0ff", "Conservation": "#39ff14", "Research": "#c084fc",
  "Fisheries": "#fbbf24", "Policy & Advocacy": "#f472b6", "Pollution": "#ff4a4a",
  "Coastal & Habitat": "#34d399", "Education": "#60a5fa", "Other": "#94a3b8",
};

export default function MapView({ projects, funderFilter, searchQuery, t, maxMarkers, minZoom, basemap, categories, categoryFilter }) {
  const mapRef = useRef(null);
  const mapObj = useRef(null);
  const clusterRef = useRef(null);
  const tileRef = useRef(null);
  const sigRef = useRef("");
  const zoomingRef = useRef(false);
  const pendingRef = useRef(null);

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
    map.addLayer(cluster);
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
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <a href="${p.url}" target="_blank" rel="noreferrer" style="font-size:11px;color:#00f0ff;font-weight:600;text-decoration:none;">${t("viewProject")} →</a>
              <button onclick="window.__biDonate && window.__biDonate('${p.id}')" data-testid="popup-donate-btn" style="font-size:10px;font-weight:600;color:#39ff14;background:rgba(57,255,20,0.08);border:1px solid rgba(57,255,20,0.4);border-radius:2px;padding:2px 8px;cursor:pointer;">${t("donate")}</button>
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
