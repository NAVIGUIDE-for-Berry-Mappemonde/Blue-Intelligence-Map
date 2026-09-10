import { useEffect, useRef } from "react";
import L from "leaflet";
import { depthRowHtml } from "./depthRow";

/**
 * Couche Mouillages (Phase 8) : marqueurs teal reconstruits quand la prop
 * anchorages change, affichés aux côtés des marinas en mode marinas.
 */
export default function useAnchoragesLayer({ mapObj, anchorClusterRef, anchorages, tRef }) {
  const anchorSigRef = useRef("");

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
            ${depthRowHtml(lat, lon, t)}
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
    // eslint-disable-next-line
  }, [anchorages]);
}
