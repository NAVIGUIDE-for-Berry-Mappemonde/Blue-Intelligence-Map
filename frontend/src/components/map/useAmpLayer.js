import { useEffect, useRef } from "react";
import api from "../../api";
import { escH, LFP_COLORS } from "./constants";

const MIN_ZOOM = 5;
const DEBOUNCE_MS = 420;

function hostLabel(url) {
  try {
    return String(url).replace(/^https?:\/\//, "").replace(/\/$/, "").slice(0, 48);
  } catch (_) {
    return String(url || "").slice(0, 48);
  }
}

function popupHtml(p, t) {
  const lfp = Number(p.lfp) || 0;
  const lfpColor = LFP_COLORS[lfp] || LFP_COLORS[0];
  const manager = p.manager_url
    ? `<div style="margin-top:8px;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:#64748b;">${escH(t("ampManagerUrl"))}</div>
        <a href="${escH(p.manager_url)}" target="_blank" rel="noreferrer" data-testid="amp-manager-url"
           style="color:#94a3b8;font-size:11px;text-decoration:none;word-break:break-all;">${escH(hostLabel(p.manager_url))}</a>
      </div>`
    : `<div style="margin-top:8px;font-size:11px;color:#64748b;">${escH(t("ampNoManagerUrl"))}</div>`;
  const visit = p.visit_url
    ? `<div style="margin-top:8px;">
        <div style="font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:#4ade80;">${escH(t("ampVisitUrl"))}</div>
        <a href="${escH(p.visit_url)}" target="_blank" rel="noreferrer" data-testid="amp-visit-url"
           style="color:#4ade80;font-size:11px;font-weight:600;text-decoration:none;word-break:break-all;">${escH(hostLabel(p.visit_url))}</a>
      </div>`
    : `<div style="margin-top:8px;font-size:11px;color:#64748b;" data-testid="amp-visit-url-missing">${escH(t("ampNoVisitUrl"))}</div>`;
  return `<div style="min-width:240px;max-width:320px;">
    <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${escH(p.name || p.site_id)}</div>
    <div style="margin-top:4px;font-size:11px;color:#94a3b8;">${escH([p.designation, p.country].filter(Boolean).join(" · "))}</div>
    <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
      <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${lfpColor};border:1px solid ${lfpColor}66;padding:2px 6px;border-radius:2px;">
        LFP ${lfp} · ${escH(t(`lfp${lfp}`))}
      </span>
    </div>
    ${p.managing_authority ? `<div style="margin-top:6px;font-size:11px;color:#cbd5e1;">${escH(p.managing_authority)}</div>` : ""}
    ${manager}
    ${visit}
    <p style="margin:10px 0 0;font-size:10px;color:#64748b;line-height:1.35;">${escH(t("mpaDisclaimer"))}</p>
  </div>`;
}

/**
 * Couche AMP : polygones ProtectedSeas chargés par bbox.
 * Popup : URL gestionnaire ≠ URL de visite.
 */
export default function useAmpLayer({
  mapObj, ampLayerRef, ampLayersById, mode, tRef, onSites, flyToAmp,
  runId = null,
}) {
  const timerRef = useRef(null);
  const lastKeyRef = useRef("");

  useEffect(() => {
    const map = mapObj.current;
    const layer = ampLayerRef.current;
    if (!map || !layer || mode !== "amp") return undefined;

    const load = async () => {
      // Run sélectionné (bouton " > " de l'onglet Map) : toutes les AMP du
      // run, quel que soit le zoom / la bbox.
      if (runId) {
        const key = `run:${runId}`;
        if (key === lastKeyRef.current) return;
        lastKeyRef.current = key;
        try {
          const { data } = await api.get(`/amp/runs/${runId}/geojson`);
          layer.clearLayers();
          if (ampLayersById?.current) ampLayersById.current.clear();
          if (data?.features?.length) layer.addData(data);
          if (onSites) onSites(data);
        } catch (_) {
          lastKeyRef.current = "";
        }
        return;
      }
      const zoom = map.getZoom();
      if (zoom < MIN_ZOOM) {
        layer.clearLayers();
        if (ampLayersById?.current) ampLayersById.current.clear();
        lastKeyRef.current = "";
        if (onSites) onSites({ type: "FeatureCollection", features: [], hint: "zoom" });
        return;
      }
      const b = map.getBounds();
      const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]
        .map((n) => n.toFixed(4)).join(",");
      const key = `${zoom}:${bbox}`;
      if (key === lastKeyRef.current) return;
      lastKeyRef.current = key;
      try {
        const { data } = await api.get("/amp", { params: { bbox } });
        layer.clearLayers();
        if (ampLayersById?.current) ampLayersById.current.clear();
        const feats = data?.features || [];
        if (feats.length) layer.addData(data);
        if (onSites) onSites(data);
      } catch (_) {
        lastKeyRef.current = "";
      }
    };

    const schedule = () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(load, DEBOUNCE_MS);
    };

    load();
    map.on("moveend", schedule);
    map.on("zoomend", schedule);
    return () => {
      map.off("moveend", schedule);
      map.off("zoomend", schedule);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [mode, mapObj, ampLayerRef, ampLayersById, onSites, tRef, runId]);

  useEffect(() => {
    if (!flyToAmp) return;
    const map = mapObj.current;
    const layer = ampLayersById?.current?.get(flyToAmp.id);
    if (!map || flyToAmp.lat == null) return;
    map.flyTo([flyToAmp.lat, flyToAmp.lon], Math.max(map.getZoom(), 8), { duration: 0.8 });
    setTimeout(() => {
      try { if (layer) layer.openPopup(); } catch (_) { /* detached */ }
    }, 850);
  }, [flyToAmp, mapObj, ampLayersById]);
}

export { popupHtml, MIN_ZOOM };
