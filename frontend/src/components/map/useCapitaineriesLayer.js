import { useEffect, useRef } from "react";
import L from "leaflet";
import { formatCapitainerieSource } from "../../lib/capitainerieSource";
import { circleOpts, POPUP_OPTS } from "./points";

const esc = (value) => String(value ?? "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const COLOR = "#38bdf8";

/**
 * Couche Capitaineries : OSM + SHOM + NOAA, pastilles canvas, sans cluster.
 */
export default function useCapitaineriesLayer({
  mapObj, clusterRef, markersById, capitaineries, tRef,
}) {
  const sigRef = useRef("");

  useEffect(() => {
    const cluster = clusterRef.current;
    const map = mapObj.current;
    if (!cluster || !map) return;
    const feats = (capitaineries && capitaineries.features) || [];
    const first = feats[0]?.properties || {};
    const last = feats[feats.length - 1]?.properties || {};
    const withContact = feats.filter((f) => f.properties?.telephone || f.properties?.canal_vhf).length;
    const sig = `${feats.length}:${withContact}:${first.id || ""}:${last.id || ""}`;
    if (sig === sigRef.current) return;
    sigRef.current = sig;
    cluster.clearLayers();
    markersById.current.clear();
    const renderer = cluster._biRenderer;
    const zoom = map.getZoom();

    const markers = feats.map((f) => {
      const [lon, lat] = f.geometry?.coordinates || [0, 0];
      const p = f.properties || {};
      const hasContact = !!(p.telephone || p.canal_vhf);
      const m = L.circleMarker([lat, lon], circleOpts(COLOR, {
        zoom, bump: hasContact ? 0.4 : 0, weight: hasContact ? 1.4 : 1,
        fillOpacity: hasContact ? 0.92 : 0.65, renderer,
      }));
      m._biBump = hasContact ? 0.4 : 0;
      m.bindPopup(
        () => {
          const t = tRef.current;
          const displayName = p.name || t("capitaineriesUnnamed");
          const website = p.website;
          const mapsUrl = p.maps_url
            || `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
              `${p.name || ""} ${lat},${lon}`.trim(),
            )}`;
          const src = formatCapitainerieSource(p.source, t);
          const phoneRow = p.telephone
            ? `<div style="font-size:12px;margin-top:6px;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("marinasPhone"))}</span>
                <a href="tel:${esc(p.telephone)}" style="color:#38bdf8;text-decoration:none;">${esc(p.telephone)}</a></div>`
            : "";
          const vhfRow = p.canal_vhf
            ? `<div style="font-size:12px;margin-top:4px;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">VHF</span>
                <span style="color:#e2e8f0;"> ${esc(p.canal_vhf)}</span></div>`
            : "";
          const siteRow = website
            ? `<div style="font-size:11px;color:#94a3b8;margin-top:6px;">
                <span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("marinasWebsite"))}</span>
                <a href="${esc(website)}" target="_blank" rel="noreferrer" style="color:#38bdf8;text-decoration:none;">${esc(String(website).replace(/^https?:\/\//, "").slice(0, 42))}</a>
              </div>`
            : "";
          return `<div style="min-width:220px;max-width:300px;" data-testid="capitainerie-popup">
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${esc(displayName)}</div>
            <div style="margin:6px 0;display:flex;gap:5px;flex-wrap:wrap;">
              <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;border:1px solid #33415555;padding:2px 6px;border-radius:2px;">${esc(src)}</span>
            </div>
            ${phoneRow}
            ${vhfRow}
            ${siteRow}
            <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <a href="${esc(mapsUrl)}" target="_blank" rel="noreferrer" data-testid="popup-maps-link"
                 style="font-size:10px;font-weight:600;color:#fff;background:rgba(56,189,248,0.18);border:1px solid rgba(56,189,248,0.45);border-radius:2px;padding:3px 10px;text-decoration:none;">
                ${esc(t("marinasGoogleMaps"))}
              </a>
              <span style="font-size:9px;color:#64748b;font-family:'JetBrains Mono',monospace;">${p.osm_id ? "OSM " + esc(p.osm_id) : (p.shom_id ? esc(p.shom_id) : "")}</span>
            </div>
          </div>`;
        },
        { ...POPUP_OPTS, maxWidth: 320 },
      );
      markersById.current.set(p.id, m);
      if (p.osm_id) markersById.current.set(p.osm_id, m);
      return m;
    });
    cluster.addLayers(markers);
    // eslint-disable-next-line
  }, [capitaineries]);
}
