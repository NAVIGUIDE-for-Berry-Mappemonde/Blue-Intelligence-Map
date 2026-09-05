import { useEffect, useRef } from "react";
import L from "leaflet";
import api from "../../api";
import { escH, flagEmoji, zoneStyle } from "./constants";

/**
 * Couches du mode Formalités : choroplèthe ZEE (chargée paresseusement à la
 * première ouverture du mode), restyle au changement de statut des zones,
 * marqueurs des Ports d'Entrée (ambre, clusterisés) et flyTo depuis la liste.
 */
export default function useFormalitiesLayers({
  mapObj, eezLayerRef, eezLayersByMrgid, zoneItemsRef, poeClusterRef,
  mode, poeZones, poePorts, flyToZone, tRef,
}) {
  const eezLoadedRef = useRef(false);
  const poeSigRef = useRef("");

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
    // eslint-disable-next-line
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
    // eslint-disable-next-line
  }, [poeZones]);

  // PoE port markers (amber dots, clustered).
  useEffect(() => {
    const cluster = poeClusterRef.current;
    if (!cluster) return;
    const feats = poePorts?.features || [];
    const sig = feats.map((f) => `${f.properties.id}|${f.properties.validated ? 1 : 0}|${f.properties.osm_confidence ?? ""}|${f.properties.spatial_anomaly ? 1 : 0}|${f.properties.noonsite_confirmed ? 1 : 0}`).join(",");
    if (sig === poeSigRef.current && cluster.getLayers().length) return;
    poeSigRef.current = sig;
    cluster.clearLayers();
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
        // Badges Bottom-Up : confiance OSM (Overpass) + anomalie spatiale (ML)
        let osmBadge = "";
        if (p.osm_confidence != null) {
          const c = Number(p.osm_confidence);
          const col = c >= 0.5 ? "#39ff14" : c > 0 ? "#fbbf24" : "#94a3b8";
          const label = c > 0
            ? `${escH(t("poeOsmConfidence"))} ${c.toFixed(2)}`
            : escH(t("poeOsmNoMatch"));
          const tags = (p.osm_tags || []).join(", ");
          osmBadge = `<span data-testid="poe-osm-badge" title="${escH(tags)}" style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${col};border:1px solid ${col}55;padding:2px 6px;border-radius:2px;">${c > 0 ? "⬢ " : "∅ "}${label}</span>`;
        }
        const anomBadge = p.spatial_anomaly
          ? `<span data-testid="poe-anomaly-badge" style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#ff4a4a;border:1px solid rgba(255,74,74,0.5);background:rgba(255,74,74,0.08);padding:2px 6px;border-radius:2px;">⚠ ${escH(t("poeAnomaly"))}</span>`
          : "";
        const nsUrl = p.noonsite_url ? escH(p.noonsite_url) : "";
        const nsBadge = p.noonsite_confirmed
          ? `<span data-testid="poe-noonsite-badge" title="${escH(t("noonsiteConfirmedTitle"))}" style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#5eead4;border:1px solid rgba(94,234,212,0.45);padding:2px 6px;border-radius:2px;">${nsUrl ? `<a href="${nsUrl}" target="_blank" rel="noreferrer" style="color:#5eead4;text-decoration:none;">` : ""}⚑ ${escH(t("noonsiteConfirmed"))}${nsUrl ? "</a>" : ""}</span>`
          : "";
        return `<div style="min-width:230px;max-width:300px;font-family:Manrope,sans-serif;">
          <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">⚓ ${escH(p.name)}</div>
          <div style="font-size:11px;color:#94a3b8;margin:3px 0 5px;">${escH(p.city || "")}${p.city ? " · " : ""}${flagEmoji(p.country_iso2)} ${escH(p.zone_name || "")}</div>
          <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:5px;">${valid}
            <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;border:1px solid #33415555;padding:2px 6px;border-radius:2px;">${escH(p.geocode_source || t("poeNotGeocoded"))}</span>
            ${osmBadge}${anomBadge}${nsBadge}
          </div>
          ${p.note ? `<div style="font-size:11px;color:#e2e8f0;line-height:1.4;margin-bottom:5px;">${escH(p.note)}</div>` : ""}
          ${srcs ? `<div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:0.08em;margin-top:4px;">${escH(t("poeSourcesTitle"))}</div>${srcs}` : ""}
          <div style="margin-top:7px;font-size:9px;color:#64748b;">${escH(t("poeGeocodeAttribution"))}${p.extracted_at ? " · " + escH(String(p.extracted_at).slice(0, 10)) : ""}</div>
        </div>`;
      }, { maxWidth: 310, maxHeight: 340, autoPan: true, autoPanPadding: [40, 40] });
      return m;
    });
    cluster.addLayers(markers);
    // eslint-disable-next-line
  }, [poePorts]);

  // FlyTo signal from FormalitiesPanel (EEZ row click)
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
    // eslint-disable-next-line
  }, [flyToZone]);
}
