import { useEffect, useRef } from "react";
import L from "leaflet";
import { remainingParts, wakeParts } from "../engine/filmWake.js";
import { worldCopyParts } from "../utils/geo.js";
import { WAKE_DONE_COLOR, WAKE_REST_COLOR } from "../layers/styles.js";

const WAKE_STYLE = {
  color: WAKE_DONE_COLOR,
  weight: 4,
  opacity: 0.92,
  pane: "route",
  interactive: false,
};

const REST_STYLE = {
  color: WAKE_REST_COLOR,
  weight: 4,
  opacity: 0.88,
  pane: "route",
  interactive: false,
};

function syncLines(store, parts, style, group) {
  while (store.current.length < parts.length) {
    store.current.push(L.polyline([], style).addTo(group));
  }
  while (store.current.length > parts.length) {
    const line = store.current.pop();
    group.removeLayer(line);
  }
  parts.forEach((coords, i) => {
    store.current[i].setLatLngs(coords.map(([lon, lat]) => [lat, lon]));
  });
}

/**
 * Accompli = bleu clair. Reste = bleu foncé. Leaflet only — no deck.gl.
 */
export function useWakeLayer(mapRef, { flat, sailNm, enabled, mapReady }) {
  const groupRef = useRef(null);
  const wakeRef = useRef([]);
  const restRef = useRef([]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !enabled) {
      groupRef.current?.remove();
      groupRef.current = null;
      wakeRef.current = [];
      restRef.current = [];
      return undefined;
    }
    const group = L.layerGroup().addTo(map);
    groupRef.current = group;
    return () => {
      group.remove();
      groupRef.current = null;
      wakeRef.current = [];
      restRef.current = [];
    };
  }, [mapRef, mapReady, enabled]);

  useEffect(() => {
    const group = groupRef.current;
    if (!group || !enabled) return;
    syncLines(restRef, worldCopyParts(remainingParts(flat, sailNm)), REST_STYLE, group);
    syncLines(wakeRef, worldCopyParts(wakeParts(flat, sailNm)), WAKE_STYLE, group);
  }, [flat, sailNm, enabled]);
}
