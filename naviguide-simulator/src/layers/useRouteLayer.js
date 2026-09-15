import { useEffect, useRef } from "react";
import L from "leaflet";
import { splitAntimeridianCoords, worldCopyCoords } from "../utils/geo.js";
import { ROUTE_CASING_COLOR, ROUTE_CASING_WEIGHT, ROUTE_MAIN_COLOR, ROUTE_MAIN_WEIGHT } from "./styles.js";

function addLine(group, coords, { color, weight, dash, pane = "route" }) {
  if (!coords || coords.length < 2) return;
  for (const part of splitAntimeridianCoords(coords)) {
    for (const copy of worldCopyCoords(part)) {
      const latlngs = copy.map(([lon, lat]) => [lat, lon]);
      L.polyline(latlngs, { color, weight, dashArray: dash, pane, interactive: true }).addTo(group);
    }
  }
}

export function useRouteLayer(mapRef, {
  segments,
  customRoute,
  drawingMode,
  drawnSegments,
  drawnFailed,
  mapReady,
  visible = true,
  hideMaritime = false,
}) {
  const groupRef = useRef(null);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return undefined;
    if (groupRef.current) groupRef.current.remove();
    const group = L.layerGroup().addTo(map);
    groupRef.current = group;

    if (drawingMode) {
      drawnSegments.forEach((s) => {
        addLine(group, s.coords, {
          color: s.failed ? "#f97316" : "#22c55e",
          weight: 3,
          dash: s.failed ? "6 6" : null,
        });
      });
      return () => group.remove();
    }

    if (!visible) {
      return () => group.remove();
    }

    if (customRoute?.features) {
      customRoute.features
        .filter((f) => f.geometry?.type === "LineString")
        .forEach((f) => {
          addLine(group, f.geometry.coordinates, { color: "#0077ff", weight: ROUTE_MAIN_WEIGHT });
        });
      return () => group.remove();
    }

    segments.forEach((s) => {
      if (!s.coords?.length) return;
      if (s.nonMaritime) {
        addLine(group, s.coords, { color: "orange", weight: 4, dash: "6 6" });
      } else if (!hideMaritime) {
        addLine(group, s.coords, { color: ROUTE_CASING_COLOR, weight: ROUTE_CASING_WEIGHT });
        addLine(group, s.coords, { color: "#0077ff", weight: ROUTE_MAIN_WEIGHT });
      }
    });

    return () => group.remove();
  }, [mapRef, mapReady, segments, customRoute, drawingMode, drawnSegments, drawnFailed, visible, hideMaritime]);

  return groupRef;
}

export { ROUTE_MAIN_COLOR };
