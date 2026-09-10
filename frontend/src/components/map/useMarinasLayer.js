import { useEffect, useRef } from "react";
import L from "leaflet";
import { depthRowHtml } from "./depthRow";

const esc = (value) => String(value ?? "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

/**
 * Couche Marinas : dump mondial OSM.
 * Point plus gros seulement si une URL Google /maps/place/ a été trouvée.
 */
export default function useMarinasLayer({ mapObj, marinaClusterRef, marinaMarkersById, marinas, tRef }) {
  const marinaSigRef = useRef("");

  useEffect(() => {
    const marinaCluster = marinaClusterRef.current;
    const map = mapObj.current;
    if (!marinaCluster || !map) return;
    const feats = (marinas && marinas.features) || [];
    const first = feats[0]?.properties || {};
    const last = feats[feats.length - 1]?.properties || {};
    const withPlace = feats.filter((f) => f.properties?.has_google_place || f.properties?.maps_place_url).length;
    const sig = `${feats.length}:${withPlace}:${first.osm_id || first.id || ""}:${last.osm_id || last.id || ""}`;
    if (sig === marinaSigRef.current) return;
    marinaSigRef.current = sig;
    marinaCluster.clearLayers();
    marinaMarkersById.current.clear();

    const markers = feats.map((f) => {
      const [lon, lat] = f.geometry?.coordinates || [0, 0];
      const p = f.properties || {};
      const hasPlace = !!(p.has_google_place || (p.maps_place_url && String(p.maps_place_url).includes("/maps/place/")));
      const m = L.circleMarker([lat, lon], {
        radius: hasPlace ? 8 : 5,
        color: "#ff4a4a",
        weight: hasPlace ? 2.5 : 2,
        fillColor: "#ff4a4a",
        fillOpacity: hasPlace ? 0.88 : 0.55,
      });
      m.bindPopup(
        () => {
          const t = tRef.current;
          const displayName = p.name || t("marinasUnnamed");
          const website = p.website;
          const mapsUrl = hasPlace
            ? p.maps_place_url
            : (p.maps_url
              || `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
                `${p.name || ""} ${lat},${lon}`.trim(),
              )}`);
          const siteRow = website
            ? `<div style="font-size:11px;color:#94a3b8;margin-top:6px;">
                <span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("marinasWebsite"))}</span>
                <a href="${esc(website)}" target="_blank" rel="noreferrer" style="color:#00f0ff;text-decoration:none;">${esc(String(website).replace(/^https?:\/\//, "").slice(0, 42))}</a>
              </div>`
            : "";
          const placeBadge = hasPlace
            ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#ff4a4a;border:1px solid #ff4a4a55;padding:2px 6px;border-radius:2px;">${esc(t("marinasGooglePlace"))}</span>`
            : "";
          return `<div style="min-width:220px;max-width:300px;">
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${esc(displayName)}</div>
            <div style="margin:6px 0;display:flex;gap:5px;flex-wrap:wrap;">
              <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;border:1px solid #33415555;padding:2px 6px;border-radius:2px;">${esc(t("marinasSourceOSM"))}</span>
              ${placeBadge}
            </div>
            ${siteRow}
            ${depthRowHtml(lat, lon, t)}
            <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <a href="${esc(mapsUrl)}" target="_blank" rel="noreferrer" data-testid="popup-maps-link"
                 style="font-size:10px;font-weight:600;color:#fff;background:rgba(255,74,74,0.18);border:1px solid rgba(255,74,74,0.45);border-radius:2px;padding:3px 10px;text-decoration:none;">
                ${esc(t("marinasGoogleMaps"))}
              </a>
              <span style="font-size:9px;color:#64748b;font-family:'JetBrains Mono',monospace;">${p.osm_id ? "OSM " + esc(p.osm_id) : ""}</span>
            </div>
          </div>`;
        },
        { maxWidth: 320, maxHeight: 400, autoPan: true, autoPanPadding: [40, 40] },
      );
      marinaMarkersById.current.set(p.id, m);
      if (p.osm_id) marinaMarkersById.current.set(p.osm_id, m);
      return m;
    });
    marinaCluster.addLayers(markers);
    // eslint-disable-next-line
  }, [marinas]);
}
