import { useEffect, useRef } from "react";
import L from "leaflet";

const esc = (value) => String(value ?? "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const COLOR = "#a78bfa";

const SOURCE_LABELS = {
  sextant: "Sextant · Ifremer/SISMER",
  odatis: "ODATIS · Data Terra",
  edmed: "EDMED · SeaDataNet",
  argo: "Argo · Coriolis",
  csr: "CSR · SeaDataNet",
};

const OCEAN_LABELS = { A: "Atlantique", P: "Pacifique", I: "Indien" };

const doiHref = (doi) => (String(doi).startsWith("http") ? doi : `https://doi.org/${doi}`);

function popupHtml(p, t, { isArgo, isCruise }) {
  const displayName = p.name || t(isCruise ? "scienceUnnamedCruise" : "scienceUnnamed");
  const kindLabel = isArgo ? t("scienceArgoFloat") : isCruise ? t("scienceCruise") : t("scienceDataset");
  const srcLabel = SOURCE_LABELS[p.source] || p.source || "";
  const providerRow = p.provider
    ? `<div style="font-size:12px;margin-top:6px;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("scienceProvider"))}</span>
        <span style="color:#e2e8f0;"> ${esc(String(p.provider).slice(0, 90))}</span></div>`
    : "";
  const abstractRow = p.abstract
    ? `<div style="font-size:11px;color:#94a3b8;margin-top:6px;line-height:1.45;max-height:110px;overflow:auto;">${esc(String(p.abstract).slice(0, 420))}${String(p.abstract).length > 420 ? "…" : ""}</div>`
    : "";
  const doiRow = p.doi
    ? `<div style="font-size:11px;margin-top:6px;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("scienceDoi"))}</span>
        <a href="${esc(doiHref(p.doi))}" target="_blank" rel="noreferrer" style="color:${COLOR};text-decoration:none;">${esc(String(p.doi).replace(/^https?:\/\/(dx\.)?doi\.org\//, "").slice(0, 48))}</a></div>`
    : "";
  const argoRows = isArgo
    ? `<div style="font-size:12px;margin-top:6px;display:flex;gap:12px;flex-wrap:wrap;">
        ${p.wmo ? `<span><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">WMO</span> <span style="color:#e2e8f0;font-family:'JetBrains Mono',monospace;">${esc(p.wmo)}</span></span>` : ""}
        ${p.cycle != null ? `<span><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("scienceCycle"))}</span> <span style="color:#e2e8f0;">${esc(p.cycle)}</span></span>` : ""}
        ${p.ocean ? `<span><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("scienceOcean"))}</span> <span style="color:#e2e8f0;">${esc(OCEAN_LABELS[p.ocean] || p.ocean)}</span></span>` : ""}
      </div>
      ${p.profile_date ? `<div style="font-size:11px;margin-top:4px;"><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("scienceLastProfile"))}</span> <span style="color:#e2e8f0;">${esc(String(p.profile_date).slice(0, 10))}</span></div>` : ""}`
    : "";
  const cruiseRows = isCruise
    ? `<div style="font-size:12px;margin-top:6px;display:flex;gap:12px;flex-wrap:wrap;">
        ${p.ship ? `<span><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("scienceShip"))}</span> <span style="color:#e2e8f0;font-family:'JetBrains Mono',monospace;">${esc(p.ship)}</span></span>` : ""}
        ${(p.start || p.end) ? `<span><span style="color:#64748b;font-family:'JetBrains Mono',monospace;font-size:9px;text-transform:uppercase;letter-spacing:0.08em;">${esc(t("scienceCruiseDates"))}</span> <span style="color:#e2e8f0;">${esc([p.start, p.end].filter(Boolean).join(" → "))}</span></span>` : ""}
      </div>`
    : "";
  const dateChip = !isArgo && p.date
    ? `<span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;border:1px solid #33415555;padding:2px 6px;border-radius:2px;">${esc(String(p.date).slice(0, 10))}</span>`
    : "";
  const portalBtn = p.url
    ? `<a href="${esc(p.url)}" target="_blank" rel="noreferrer" data-testid="popup-science-portal"
         style="font-size:10px;font-weight:600;color:#fff;background:rgba(167,139,250,0.18);border:1px solid rgba(167,139,250,0.45);border-radius:2px;padding:3px 10px;text-decoration:none;">
        ${esc(t("scienceOpenPortal"))}
      </a>`
    : "";
  return `<div style="min-width:230px;max-width:310px;" data-testid="science-popup">
    <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:13px;color:#fff;line-height:1.3;">${esc(displayName)}</div>
    <div style="margin:6px 0;display:flex;gap:5px;flex-wrap:wrap;">
      <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:${COLOR};border:1px solid rgba(167,139,250,0.4);padding:2px 6px;border-radius:2px;">${esc(kindLabel)}</span>
      <span style="font-family:'JetBrains Mono',monospace;font-size:9px;color:#94a3b8;border:1px solid #33415555;padding:2px 6px;border-radius:2px;">${esc(srcLabel)}</span>
      ${dateChip}
    </div>
    ${providerRow}
    ${argoRows}
    ${cruiseRows}
    ${abstractRow}
    ${doiRow}
    <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      ${portalBtn}
    </div>
  </div>`;
}

/**
 * Couche Science : datasets (disque plein), Argo (anneau), campagnes CSR
 * (polylines hors cluster). Popup : organisme, résumé, DOI, lien portail.
 */
export default function useScienceLayer({
  mapObj, clusterRef, tracksLayerRef, markersById, science, tRef,
}) {
  const sigRef = useRef("");

  useEffect(() => {
    const cluster = clusterRef.current;
    const map = mapObj.current;
    const tracksLayer = tracksLayerRef && tracksLayerRef.current;
    if (!cluster || !map) return;
    const feats = (science && science.features) || [];
    const first = feats[0]?.properties || {};
    const last = feats[feats.length - 1]?.properties || {};
    const argoCount = feats.filter((f) => f.properties?.kind === "argo_float").length;
    const cruiseCount = feats.filter((f) => f.properties?.kind === "cruise").length;
    const sig = `${feats.length}:${argoCount}:${cruiseCount}:${first.id || ""}:${last.id || ""}`;
    if (sig === sigRef.current) return;
    sigRef.current = sig;
    cluster.clearLayers();
    if (tracksLayer) tracksLayer.clearLayers();
    markersById.current.clear();

    const markers = [];
    feats.forEach((f) => {
      const p = f.properties || {};
      const isArgo = p.kind === "argo_float";
      const isCruise = p.kind === "cruise";
      const popupOpts = { maxWidth: 330, maxHeight: 420, autoPan: true, autoPanPadding: [40, 40] };
      if (isCruise && f.geometry?.type === "LineString") {
        const latlngs = (f.geometry.coordinates || [])
          .filter((pt) => Array.isArray(pt) && pt.length >= 2)
          .map(([ln, lt]) => [lt, ln]);
        if (latlngs.length < 2) return;
        const line = L.polyline(latlngs, {
          color: COLOR, weight: 2.5, opacity: 0.85, pane: "science-tracks",
        });
        line.bindPopup(() => popupHtml(p, tRef.current, { isArgo: false, isCruise: true }), popupOpts);
        if (tracksLayer) tracksLayer.addLayer(line);
        markersById.current.set(p.id, line);
        return;
      }
      const [lon, lat] = f.geometry?.coordinates || [0, 0];
      const m = L.circleMarker([lat, lon], isArgo
        ? { radius: 5, color: COLOR, weight: 2, fillColor: COLOR, fillOpacity: 0.25 }
        : isCruise
          ? { radius: 6, color: COLOR, weight: 2, fillColor: COLOR, fillOpacity: 0.45 }
          : { radius: 6, color: COLOR, weight: 2, fillColor: COLOR, fillOpacity: 0.85 });
      m.bindPopup(() => popupHtml(p, tRef.current, { isArgo, isCruise }), popupOpts);
      markersById.current.set(p.id, m);
      markers.push(m);
    });
    cluster.addLayers(markers);
    // eslint-disable-next-line
  }, [science]);
}
