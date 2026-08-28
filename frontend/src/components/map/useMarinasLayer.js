import { useEffect, useRef } from "react";
import L from "leaflet";

/**
 * Couche Marinas : reconstruit les marqueurs rouges (rayon selon priorité)
 * quand la prop marinas change. Les popups lisent tRef.current à l'ouverture
 * (bascule FR ↔ EN sans reconstruire les marqueurs).
 */
export default function useMarinasLayer({ mapObj, marinaClusterRef, marinaMarkersById, marinas, tRef }) {
  const marinaSigRef = useRef("");

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

      // bindPopup(FN) reads tRef.current lazily so FR ↔ EN switching updates
      // every next popup open, without rebuilding markers.
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
        { maxWidth: 320, maxHeight: 400, autoPan: true, autoPanPadding: [40, 40] },
      );
      marinaMarkersById.current.set(p.id, m);
      return m;
    });
    marinaCluster.addLayers(markers);
    // eslint-disable-next-line
  }, [marinas]);
}
