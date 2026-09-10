import { useEffect, useRef } from "react";
import L from "leaflet";

/** Couches WMS EMODnet (tuiles image — pas de CORS, GetMap côté navigateur). */
export const SCIENCE_WMS_LAYERS = [
  {
    id: "bathymetry",
    url: "https://ows.emodnet-bathymetry.eu/wms",
    layers: "mean_multicolour",
    opacity: 0.6,
    attribution: "EMODnet Bathymetry",
  },
  {
    id: "substrate",
    url: "https://drive.emodnet-geology.eu/geoserver/gtk/wms",
    layers: "seabed_substrate_1m",
    opacity: 0.5,
    attribution: "EMODnet Geology",
  },
  {
    id: "cables",
    url: "https://ows.emodnet-humanactivities.eu/wms",
    layers: "telecablesactual,powercables",
    opacity: 0.9,
    attribution: "EMODnet Human Activities",
  },
];

/**
 * Couches de fond WMS du mode Science (bathymétrie, substrat, câbles).
 * Visible uniquement en mode science, pane sous les marqueurs.
 */
export default function useScienceWms({ mapObj, mode, enabled }) {
  const layersRef = useRef({});

  useEffect(() => {
    const map = mapObj.current;
    if (!map) return;
    if (!map.getPane("science-wms")) {
      map.createPane("science-wms");
      map.getPane("science-wms").style.zIndex = 350;
    }
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
            opacity: spec.opacity,
            pane: "science-wms",
            attribution: spec.attribution,
            maxZoom: 16,
          });
          layersRef.current[spec.id] = lyr;
        }
        if (!map.hasLayer(lyr)) map.addLayer(lyr);
      } else if (lyr && map.hasLayer(lyr)) {
        map.removeLayer(lyr);
      }
    });
  }, [mapObj, mode, enabled]);
}
