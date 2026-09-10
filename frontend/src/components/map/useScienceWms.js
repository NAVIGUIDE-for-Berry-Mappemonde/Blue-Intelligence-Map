import { useEffect, useRef } from "react";
import L from "leaflet";

/**
 * Trois étages WMS distincts (du bas vers le haut) :
 *   1. bathymétrie  — aplat de profondeur
 *   2. nature des fonds
 *   3. câbles sous-marins
 * Chaque couche a son propre pane Leaflet : elles ne peuvent plus
 * s'écraser l'une l'autre.
 */
export const SCIENCE_WMS_LAYERS = [
  {
    id: "bathymetry",
    url: "https://ows.emodnet-bathymetry.eu/wms",
    layers: "mean_multicolour",
    opacity: 0.5,
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

/** z-index : plus le chiffre est haut, plus la couche est devant. */
export const SCIENCE_WMS_PANES = {
  "science-wms-bathy": 250,
  "science-wms-substrate": 310,
  "science-wms-cables": 370,
};

export function ensureWmsPanes(map) {
  if (!map) return;
  Object.entries(SCIENCE_WMS_PANES).forEach(([name, z]) => {
    if (!map.getPane(name)) map.createPane(name);
    const pane = map.getPane(name);
    pane.style.zIndex = String(z);
    pane.style.pointerEvents = "none";
    pane.setAttribute("data-wms-floor", name.replace("science-wms-", ""));
  });
}

function parkLayerInPane(map, lyr, paneName) {
  const pane = map.getPane(paneName);
  const el = lyr && lyr._container;
  if (!pane || !el) return;
  if (el.parentNode !== pane) pane.appendChild(el);
}

function wmsDebug() {
  if (typeof window === "undefined") return { errors: [], loads: {}, floors: {} };
  window.__biDebug = window.__biDebug || {};
  if (!window.__biDebug.wms) {
    window.__biDebug.wms = { errors: [], loads: {}, enabled: {}, floors: {} };
  }
  return window.__biDebug.wms;
}

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
    dbg.floors = {};

    SCIENCE_WMS_LAYERS.forEach((spec) => {
      const on = mode === "science" && !!(enabled && enabled[spec.id]);
      let lyr = layersRef.current[spec.id];

      if (lyr && lyr.options.pane !== spec.pane) {
        if (map.hasLayer(lyr)) map.removeLayer(lyr);
        layersRef.current[spec.id] = null;
        lyr = null;
      }

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
        parkLayerInPane(map, lyr, spec.pane);
        const parent = lyr._container && lyr._container.parentNode;
        dbg.floors[spec.id] = parent ? parent.getAttribute("data-wms-floor") : null;
      } else if (lyr && map.hasLayer(lyr)) {
        map.removeLayer(lyr);
      }
    });
  }, [mapObj, mode, enabled, bathy, substrate, cables]);
}
