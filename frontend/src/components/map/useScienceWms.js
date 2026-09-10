import { useEffect, useRef } from "react";
import L from "leaflet";

/**
 * Couches WMS EMODnet. Panes séparés : la bathymétrie est un aplat opaque
 * qui masquait câbles et substrat quand tout partageait le même pane.
 * Ordre : bathymétrie (sous) → substrat → câbles (dessus).
 */
export const SCIENCE_WMS_LAYERS = [
  {
    id: "bathymetry",
    url: "https://ows.emodnet-bathymetry.eu/wms",
    layers: "mean_multicolour",
    opacity: 0.45,
    pane: "science-wms-bathy",
    attribution: "EMODnet Bathymetry",
  },
  {
    id: "substrate",
    url: "https://drive.emodnet-geology.eu/geoserver/gtk/wms",
    layers: "seabed_substrate_1m",
    opacity: 0.75,
    pane: "science-wms-substrate",
    attribution: "EMODnet Geology",
  },
  {
    id: "cables",
    url: "https://ows.emodnet-humanactivities.eu/wms",
    layers: "telecablesactual,powercables",
    opacity: 1,
    pane: "science-wms-cables",
    attribution: "EMODnet Human Activities",
  },
];

export const SCIENCE_WMS_PANES = {
  "science-wms-bathy": 350,
  "science-wms-substrate": 356,
  "science-wms-cables": 365,
};

function ensureWmsPanes(map) {
  Object.entries(SCIENCE_WMS_PANES).forEach(([name, z]) => {
    if (!map.getPane(name)) map.createPane(name);
    const pane = map.getPane(name);
    pane.style.zIndex = String(z);
    pane.style.pointerEvents = "none";
  });
}

function wmsDebug() {
  if (typeof window === "undefined") return { errors: [], loads: {} };
  window.__biDebug = window.__biDebug || {};
  if (!window.__biDebug.wms) {
    window.__biDebug.wms = { errors: [], loads: {}, enabled: {} };
  }
  return window.__biDebug.wms;
}

/**
 * Couches de fond WMS du mode Science.
 * Visible uniquement en mode science.
 */
export default function useScienceWms({ mapObj, mode, enabled }) {
  const layersRef = useRef({});
  const bathy = !!(enabled && enabled.bathymetry);
  const substrate = !!(enabled && enabled.substrate);
  const cables = !!(enabled && enabled.cables);

  useEffect(() => {
    const map = mapObj.current;
    if (!map) return;
    ensureWmsPanes(map);
    const dbg = wmsDebug();
    dbg.enabled = { bathymetry: bathy, substrate, cables };

    SCIENCE_WMS_LAYERS.forEach((spec) => {
      const on = mode === "science" && !!(enabled && enabled[spec.id]);
      let lyr = layersRef.current[spec.id];
      if (on) {
        if (!lyr) {
          lyr = L.tileLayer.wms(spec.url, {
            layers: spec.layers,
            format: "image/png",
            transparent: true,
            version: "1.1.1",
            uppercase: false,
            opacity: spec.opacity,
            pane: spec.pane,
            attribution: spec.attribution,
            maxZoom: 18,
            className: `bi-wms-${spec.id}`,
          });
          lyr.on("tileerror", (e) => {
            const url = (e.tile && e.tile.src) || "";
            dbg.errors.push({ id: spec.id, url: url.slice(0, 220), ts: Date.now() });
            if (dbg.errors.length > 30) dbg.errors.shift();
          });
          lyr.on("tileload", () => {
            dbg.loads[spec.id] = (dbg.loads[spec.id] || 0) + 1;
          });
          layersRef.current[spec.id] = lyr;
        }
        if (!map.hasLayer(lyr)) map.addLayer(lyr);
        try { lyr.bringToFront(); } catch (_) { /* pane gère le z-order */ }
      } else if (lyr && map.hasLayer(lyr)) {
        map.removeLayer(lyr);
      }
    });
  }, [mapObj, mode, enabled, bathy, substrate, cables]);
}
