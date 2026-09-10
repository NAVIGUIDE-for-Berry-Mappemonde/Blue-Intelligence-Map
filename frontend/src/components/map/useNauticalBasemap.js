import { useEffect, useRef, useState } from "react";
import L from "leaflet";

import { BASEMAPS } from "./basemaps";

/**
 * Charge MapLibre GL + le protocole pmtiles:// une seule fois, à la demande
 * (~800 Ko : rien n'est payé tant que l'utilisateur reste sur les fonds raster).
 * pmtiles:// lit l'archive auto-hébergée par plages d'octets — aucun serveur
 * de tuiles nécessaire, nginx statique suffit.
 */
let glLoader = null;
function loadGl() {
  if (!glLoader) {
    glLoader = (async () => {
      // Un seul Promise.all : des imports séquentiels feraient la queue
      // derrière les requêtes API (6 connexions HTTP/1.1 par origine).
      const [maplibreModule, , pmtilesModule] = await Promise.all([
        import("maplibre-gl"),
        import("maplibre-gl/dist/maplibre-gl.css"),
        import("pmtiles"),
        import("@maplibre/maplibre-gl-leaflet"),
      ]);
      // maplibre-gl v6 est un module ESM à exports nommés, sans default.
      const maplibregl = maplibreModule.default ?? maplibreModule;
      const protocol = new pmtilesModule.Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      return maplibregl;
    })();
    // Un échec ne doit pas rester en cache : le prochain passage retentera.
    glLoader.catch(() => { glLoader = null; });
  }
  return glLoader;
}

/**
 * Bascule fond raster (Esri) ↔ carte marine vectorielle (Open Waters: Seamap).
 * Retourne `true` quand la carte marine est affichée — l'appelant montre alors
 * l'avertissement « Ne convient pas à la navigation ».
 */
export default function useNauticalBasemap({ mapObj, tileRef, basemap }) {
  const glRef = useRef(null);
  const [nauticalActive, setNauticalActive] = useState(false);

  // Préchargement dès le montage : sur HTTP/1.1 le navigateur n'a que
  // 6 connexions par origine, vite saturées par les requêtes API longues.
  // Demandé plus tard (au clic), le chunk maplibre resterait en file
  // d'attente derrière elles jusqu'au timeout webpack.
  useEffect(() => {
    loadGl().catch(() => {});
  }, []);

  useEffect(() => {
    const map = mapObj.current;
    if (!map) return undefined;
    const conf = BASEMAPS[basemap] || BASEMAPS.dark;
    let cancelled = false;

    if (conf.kind === "gl") {
      loadGl()
        .then(() => {
          if (cancelled || !mapObj.current) return;
          const m = mapObj.current;
          if (!glRef.current) {
            glRef.current = L.maplibreGL({
              style: conf.styleUrl,
              pane: "basemap-gl",
              attribution: conf.attribution,
            });
          }
          if (tileRef.current && m.hasLayer(tileRef.current)) {
            m.removeLayer(tileRef.current);
          }
          if (!m.hasLayer(glRef.current)) glRef.current.addTo(m);
          setNauticalActive(true);
        })
        .catch((err) => {
          // maplibre indisponible (offline…) : on reste sur le raster courant.
          console.error("[carte marine] chargement impossible :", err);
          setNauticalActive(false);
        });
    } else {
      if (glRef.current && map.hasLayer(glRef.current)) {
        map.removeLayer(glRef.current);
      }
      if (tileRef.current) {
        tileRef.current.setUrl(conf.url);
        if (!map.hasLayer(tileRef.current)) tileRef.current.addTo(map);
      }
      setNauticalActive(false);
    }
    return () => { cancelled = true; };
    // eslint-disable-next-line
  }, [basemap]);

  return nauticalActive;
}
