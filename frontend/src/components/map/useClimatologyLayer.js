import { useEffect, useRef } from "react";
import L from "leaflet";
import api from "../../api";
import { POPUP_OPTS } from "./points";

const COLOR = "#2dd4bf";

const esc = (value) => String(value ?? "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

function roseSvg(p) {
  const ml = Number(p.wind_direction_from_deg) || 0;
  const kn = Number(p.wind_speed_knots) || 0;
  const calm = Number(p.calm_pct) || 0;
  const gale = Number(p.gale_pct) || 0;
  const centre = gale >= 8 ? "#ef4444" : calm >= 20 ? "#38bdf8" : COLOR;
  const petals = (p.directions_from || []).map((d) => {
    const rad = ((Number(d.dir_deg) || 0) * Math.PI) / 180;
    const len = Math.max(4, Math.min(14, (Number(d.pct) || 0) * 0.28));
    const x2 = 16 + Math.sin(rad) * len;
    const y2 = 16 - Math.cos(rad) * len;
    return `<line x1="16" y1="16" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${COLOR}" stroke-width="1.4" stroke-opacity="0.85" />`;
  });
  if (!petals.length) {
    const len = Math.max(6, Math.min(18, kn));
    const rad = (ml * Math.PI) / 180;
    const x2 = 16 + Math.sin(rad) * len;
    const y2 = 16 - Math.cos(rad) * len;
    petals.push(`<line x1="16" y1="16" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${COLOR}" stroke-width="1.6" />`);
  }
  return `<svg width="32" height="32" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
    ${petals.join("")}
    <circle cx="16" cy="16" r="3.2" fill="${centre}" />
  </svg>`;
}

function currentIcon(p) {
  const to = Number(p.direction_to_deg) || 0;
  return L.divIcon({
    className: "bi-climo-arrow",
    html: `<div style="width:18px;height:18px;transform:rotate(${to}deg);color:${COLOR};font-size:14px;line-height:18px;text-align:center;">↑</div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function waveColor(hs, stat) {
  if (stat === "p90") {
    if (hs >= 4) return "#7f1d1d";
    if (hs >= 2.5) return "#b45309";
    return "#0f766e";
  }
  if (hs >= 3) return "#155e75";
  if (hs >= 1.5) return "#0d9488";
  return "#5eead4";
}

function popupHtml(kind, p, t) {
  const rows = [];
  if (kind === "wind") {
    rows.push(`${esc(t("climoMostLikely"))}: ${esc(p.wind_speed_knots)} kn / ${esc(p.wind_direction_from_deg)}°`);
    rows.push(`${esc(t("climoAverage"))}: ${esc(p.vector_mean_knots)} kn / ${esc(p.vector_mean_from_deg)}°`);
    rows.push(`calm ${esc(p.calm_pct)}% · gale ${esc(p.gale_pct)}% · n=${esc(p.sample_count)}`);
  } else if (kind === "wave") {
    rows.push(`Hs ${esc(p.stat)}: ${esc(p.hs_m)} m`);
    if (p.stat === "p90") rows.push(esc(t("climoWaveP90Hint")));
  } else if (kind === "current") {
    rows.push(`${esc(p.speed_knots)} kn → ${esc(p.direction_to_deg)}°`);
    if (p.below_threshold) rows.push("below_threshold");
  } else if (kind === "cyclones") {
    rows.push(`${esc(p.name || p.sid)} · ${esc(p.season)} · ${esc(p.basin)}`);
    rows.push(`max ${esc(p.max_wind_kn)} kn · ${esc(p.wind_source || "")}`);
  }
  return `<div style="min-width:200px;max-width:280px;" data-testid="climatology-popup">
    <div style="font-weight:700;color:#fff;font-size:12px;">${esc(t("modeClimatologyFull"))}</div>
    <div style="font-family:monospace;font-size:9px;color:${COLOR};margin:4px 0;">kind: climatology · month ${esc(p.month)}</div>
    ${rows.map((r) => `<div style="font-size:11px;color:#e2e8f0;margin-top:3px;">${r}</div>`).join("")}
    <div style="font-size:10px;color:#94a3b8;margin-top:8px;">${esc(t("climoDisclaimer"))}</div>
  </div>`;
}

/**
 * Couches du 7ᵉ mode uniquement. pointer-events none sur les panes :
 * le clic carte interroge /point (pas un overlay sur les autres modes).
 */
export default function useClimatologyLayer({
  mapObj, mode, month, filters, waveStat, tRef, onPoint,
}) {
  const layersRef = useRef({ wind: null, wave: null, current: null, cyclones: null });
  const clickRef = useRef(null);

  useEffect(() => {
    const map = mapObj.current;
    if (!map) return undefined;
    const on = mode === "climatology";
    Object.values(layersRef.current).forEach((lyr) => {
      if (lyr && map.hasLayer(lyr)) map.removeLayer(lyr);
    });
    if (!on) return undefined;

    let cancelled = false;
    const popupOpts = { ...POPUP_OPTS, maxWidth: 300 };

    const silent = (fn) => fn().catch(() => undefined);

    const loadWind = async () => {
      const { data } = await api.get("/climatology/wind.geojson", { params: { month, spacing_deg: 2 } });
      if (cancelled) return;
      const group = L.layerGroup();
      (data.features || []).forEach((f) => {
        const [lon, lat] = f.geometry?.coordinates || [];
        const p = f.properties || {};
        const icon = L.divIcon({
          className: "bi-climo-rose",
          html: roseSvg(p),
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        });
        const m = L.marker([lat, lon], { icon, pane: "climatology-vector", interactive: false });
        m.bindPopup(() => popupHtml("wind", p, tRef.current), popupOpts);
        group.addLayer(m);
      });
      layersRef.current.wind = group;
      group.addTo(map);
    };

    const loadWave = async () => {
      const { data } = await api.get("/climatology/wave.geojson", {
        params: { month, stat: waveStat, spacing_deg: 2 },
      });
      if (cancelled) return;
      const group = L.layerGroup();
      (data.features || []).forEach((f) => {
        const [lon, lat] = f.geometry?.coordinates || [];
        const p = f.properties || {};
        const c = L.circleMarker([lat, lon], {
          pane: "climatology-raster",
          radius: 5,
          color: waveColor(Number(p.hs_m) || 0, p.stat),
          fillColor: waveColor(Number(p.hs_m) || 0, p.stat),
          fillOpacity: 0.55,
          weight: 0,
          interactive: false,
        });
        c.bindPopup(() => popupHtml("wave", p, tRef.current), popupOpts);
        group.addLayer(c);
      });
      layersRef.current.wave = group;
      group.addTo(map);
    };

    const loadCurrent = async () => {
      const { data } = await api.get("/climatology/current.geojson", { params: { month, spacing_deg: 2 } });
      if (cancelled) return;
      const group = L.layerGroup();
      (data.features || []).forEach((f) => {
        const [lon, lat] = f.geometry?.coordinates || [];
        const p = f.properties || {};
        if (p.below_threshold) return;
        const m = L.marker([lat, lon], {
          icon: currentIcon(p),
          pane: "climatology-vector",
          interactive: false,
        });
        m.bindPopup(() => popupHtml("current", p, tRef.current), popupOpts);
        group.addLayer(m);
      });
      layersRef.current.current = group;
      group.addTo(map);
    };

    const loadCyclones = async () => {
      const { data } = await api.get("/climatology/cyclones.geojson", { params: { month } });
      if (cancelled) return;
      const group = L.layerGroup();
      (data.features || []).forEach((f) => {
        const coords = (f.geometry?.coordinates || []).map(([ln, lt]) => [lt, ln]);
        if (coords.length < 2) return;
        const p = f.properties || {};
        const line = L.polyline(coords, {
          pane: "climatology-vector",
          color: p.color || COLOR,
          weight: 1.6,
          opacity: 0.75,
          interactive: false,
        });
        line.bindPopup(() => popupHtml("cyclones", p, tRef.current), popupOpts);
        group.addLayer(line);
      });
      layersRef.current.cyclones = group;
      group.addTo(map);
    };

    const load = async () => {
      const jobs = [];
      if (filters && filters.wind) jobs.push(silent(loadWind));
      if (filters && filters.wave) jobs.push(silent(loadWave));
      if (filters && filters.current) jobs.push(silent(loadCurrent));
      if (filters && filters.cyclones) jobs.push(silent(loadCyclones));
      await Promise.all(jobs);
    };
    load();

    const onClick = (ev) => {
      const { lat, lng } = ev.latlng || {};
      if (lat == null) return;
      api.get("/climatology/point", { params: { lat, lon: lng, month } })
        .then(({ data }) => {
          if (onPoint) onPoint(data);
          const html = `<div data-testid="climatology-map-popup" style="min-width:210px;">
            <div style="font-weight:700;color:#fff;">${esc(tRef.current("modeClimatologyFull"))}</div>
            <div style="font-family:monospace;font-size:9px;color:${COLOR};margin:4px 0;">kind: ${esc(data.kind)} · month ${esc(data.month)}</div>
            <div style="font-size:11px;color:#e2e8f0;">${esc(data.coordinates?.cell_selection)}</div>
            <div style="font-size:10px;color:#fde68a;margin-top:8px;">${esc(tRef.current("climoDisclaimer"))}</div>
          </div>`;
          L.popup({ ...popupOpts, className: "bi-climatology-popup" })
            .setLatLng(ev.latlng)
            .setContent(html)
            .openOn(map);
        })
        .catch(() => {});
    };
    clickRef.current = onClick;
    map.on("click", onClick);

    return () => {
      cancelled = true;
      map.off("click", onClick);
      Object.values(layersRef.current).forEach((lyr) => {
        if (lyr && map.hasLayer(lyr)) map.removeLayer(lyr);
      });
      layersRef.current = { wind: null, wave: null, current: null, cyclones: null };
    };
  }, [mapObj, mode, month, filters, waveStat, tRef, onPoint]);
}
