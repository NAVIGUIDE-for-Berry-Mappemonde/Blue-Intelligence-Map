import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet.markercluster";

export default function MapView({ projects, funderFilter, t, maxMarkers, minZoom }) {
  const mapRef = useRef(null);
  const mapObj = useRef(null);
  const clusterRef = useRef(null);

  useEffect(() => {
    if (mapObj.current) return;
    const map = L.map(mapRef.current, {
      center: [20, 0],
      zoom: 2.5,
      minZoom: minZoom || 2,
      worldCopyJump: true,
      zoomControl: true,
    });
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: "abcd",
      maxZoom: 19,
    }).addTo(map);
    const cluster = L.markerClusterGroup({
      maxClusterRadius: 50,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster" style="width:34px;height:34px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [34, 34],
      }),
    });
    map.addLayer(cluster);
    mapObj.current = map;
    clusterRef.current = cluster;
  }, [minZoom]);

  useEffect(() => {
    const cluster = clusterRef.current;
    if (!cluster) return;
    cluster.clearLayers();
    const features = (projects.features || [])
      .filter((f) => funderFilter === "All" || (f.properties.funder || "").includes(funderFilter))
      .slice(0, maxMarkers || 1000);
    features.forEach((f) => {
      const [lon, lat] = f.geometry.coordinates;
      const p = f.properties;
      const marker = L.circleMarker([lat, lon], {
        radius: 7,
        color: "#00f0ff",
        weight: 2,
        fillColor: "#0891b2",
        fillOpacity: 0.7,
      });
      const img = p.image ? `<img src="${p.image}" referrerpolicy="no-referrer" style="width:100%;height:110px;object-fit:cover;border-radius:3px;margin-bottom:8px;" onerror="this.remove()" />` : "";
      const snapped = p.snapped ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#fbbf24;border:1px solid #fbbf2455;padding:1px 5px;border-radius:2px;margin-left:6px;">${t("snappedBadge")}</span>` : "";
      marker.bindPopup(`
        <div style="min-width:220px;max-width:270px;">
          ${img}
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${p.title}</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#c084fc;margin:4px 0;">${p.funder}${snapped}</div>
          <div style="font-size:11px;color:#94a3b8;line-height:1.45;margin-bottom:6px;">${p.description || ""}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <a href="${p.url}" target="_blank" rel="noreferrer" style="font-size:11px;color:#00f0ff;font-weight:600;text-decoration:none;">${t("viewProject")} →</a>
            ${p.s_ocean != null ? `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;color:#39ff14;">S<sub>ocean</sub> ${p.s_ocean}</span>` : ""}
          </div>
        </div>
      `, { maxWidth: 280 });
      cluster.addLayer(marker);
    });
  }, [projects, funderFilter, maxMarkers, t]);

  return <div ref={mapRef} data-testid="map-container" className="w-full h-full" />;
}
