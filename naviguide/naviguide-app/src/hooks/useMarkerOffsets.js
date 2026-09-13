/**
 * useMarkerOffsets — décalages pixel plafonnés pour les drapeaux d'escale.
 * Les points intermédiaires restent collés à leur coordonnée.
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { computeMarkerOffsets, projectRouteSegments } from "../utils/markerOffsets";

const DEBOUNCE_MS = 120;

export function useMarkerOffsets(points, mapRef, routeCoords = []) {
  const [offsets, setOffsets] = useState(() => points.map(() => [0, 0]));
  const timerRef = useRef(null);

  const compute = useCallback(() => {
    const map = mapRef.current?.getMap();
    if (!map || !points.length) return;

    const project = (lon, lat) => {
      const pt = map.project([lon, lat]);
      return { x: pt.x, y: pt.y };
    };
    const routeSegs = projectRouteSegments(routeCoords, project);
    setOffsets(computeMarkerOffsets(points, project, routeSegs));
  }, [points, mapRef, routeCoords]);

  useEffect(() => {
    if (!points.length) return;

    const schedule = () => {
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(compute, DEBOUNCE_MS);
    };

    const attachListeners = () => {
      const map = mapRef.current?.getMap();
      if (!map) return false;
      map.on("zoomend", schedule);
      map.on("moveend", schedule);
      compute();
      return true;
    };

    if (!attachListeners()) {
      const poll = setInterval(() => {
        if (attachListeners()) clearInterval(poll);
      }, 200);
      return () => {
        clearInterval(poll);
        clearTimeout(timerRef.current);
      };
    }

    return () => {
      clearTimeout(timerRef.current);
      const map = mapRef.current?.getMap();
      if (map) {
        map.off("zoomend", schedule);
        map.off("moveend", schedule);
      }
    };
  }, [compute, mapRef, points]);

  return offsets;
}
