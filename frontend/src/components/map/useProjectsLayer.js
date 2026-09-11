import { useEffect, useRef } from "react";
import L from "leaflet";
import { circleOpts, POPUP_OPTS } from "./points";

/**
 * Couche Projets : pastilles canvas, filtrées, sans plafond ni cluster.
 */
export default function useProjectsLayer({
  mapObj, clusterRef, zoomingRef, pendingRef, markersById,
  projects, funderFilter, categoryFilter, searchQuery, colorOf, tRef,
}) {
  const sigRef = useRef("");

  useEffect(() => {
    const cluster = clusterRef.current;
    const map = mapObj.current;
    if (!cluster || !map) return;
    const q = (searchQuery || "").toLowerCase();
    const features = (projects.features || []).filter((f) => (
      (funderFilter === "All" || (f.properties.funder || "").includes(funderFilter))
      && (categoryFilter === "All" || f.properties.category_group === categoryFilter)
      && (!q || `${f.properties.title} ${f.properties.description} ${f.properties.funder} ${f.properties.location || ""}`.toLowerCase().includes(q))
    ));
    const sig = `${features.length}|${funderFilter}|${categoryFilter}|${q}|${features.map((f) => f.properties.id).join(",")}`;
    if (sig === sigRef.current) return;
    sigRef.current = sig;

    const apply = () => {
      map.closePopup();
      cluster.clearLayers();
      if (markersById?.current) markersById.current.clear();
      const renderer = cluster._biRenderer;
      const zoom = map.getZoom();
      const markers = features.map((f) => {
        const [lon, lat] = f.geometry.coordinates;
        const p = f.properties;
        const col = colorOf(p.category_group);
        const marker = L.circleMarker([lat, lon], circleOpts(col, { zoom, renderer }));
        const img = p.image ? `<img src="${p.image}" referrerpolicy="no-referrer" style="width:100%;height:110px;object-fit:cover;border-radius:3px;margin-bottom:8px;" onerror="this.remove()" />` : "";
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
        }, POPUP_OPTS);
        if (markersById?.current && p.id) markersById.current.set(p.id, marker);
        return marker;
      });
      cluster.addLayers(markers);
    };

    if (zoomingRef.current) {
      pendingRef.current = apply;
    } else {
      apply();
    }
  }, [projects, funderFilter, categoryFilter, searchQuery]); // eslint-disable-line
}
