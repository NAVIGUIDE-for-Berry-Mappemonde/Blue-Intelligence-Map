import { useEffect, useRef } from "react";
import L from "leaflet";
import api from "../../api";
import {
  ESCALE_FILL, ESCALE_STROKE, INTERMEDIATE_FILL, INTERMEDIATE_STROKE,
  ROUTE_CASING_COLOR, ROUTE_CASING_WEIGHT, ROUTE_MAIN_COLOR, ROUTE_MAIN_WEIGHT,
} from "./constants";
import { POPUP_OPTS } from "./points";

/**
 * Couche route Berry-Mappemonde (statique, officielle) : polylignes à double
 * trait (casing sombre + trait clair) dans le pane "route" (sous les clusters),
 * points intermédiaires muets et escales cliquables.
 */
export default function useRouteLayer(mapObj, tRef, t) {
  const routeLayerRef = useRef(null);
  const routeLoadedRef = useRef(false);

  useEffect(() => {
    const map = mapObj.current;
    if (!map || routeLoadedRef.current) return;
    routeLoadedRef.current = true;
    (async () => {
      let data;
      try {
        const res = await api.get("/route");
        data = res.data;
      } catch (e) {
        routeLoadedRef.current = false; // allow retry on next mount
        return;
      }
      const group = L.layerGroup();
      const feats = (data && data.features) || [];
      // Two-pass draw so lines sit UNDER waypoints: casings first, then main strokes, then waypoints
      const escales = [];
      const intermediates = [];
      feats.forEach((f) => {
        const g = f.geometry || {};
        const p = f.properties || {};
        if (g.type === "LineString") {
          const latlngs = g.coordinates.map(([lng, lat]) => [lat, lng]);
          const isOverland = p.type === "overland";
          // dark casing for contrast on light basemap — drawn in the "route" pane so
          // it sits UNDER the marker clusters (fixes cluster 55 over Europe hiding the leg).
          L.polyline(latlngs, {
            color: ROUTE_CASING_COLOR,
            weight: ROUTE_CASING_WEIGHT,
            opacity: 0.35,
            lineCap: "round",
            lineJoin: "round",
            interactive: false,
            fill: false,
            pane: "route",
          }).addTo(group);
          // main stroke on top of the casing but still in the "route" pane
          L.polyline(latlngs, {
            color: ROUTE_MAIN_COLOR,
            weight: ROUTE_MAIN_WEIGHT,
            opacity: 0.95,
            dashArray: isOverland ? "6 6" : null,
            lineCap: "round",
            lineJoin: "round",
            interactive: false,   // no hover tooltip on route segments
            fill: false,
            pane: "route",
          }).addTo(group);
        } else if (g.type === "Point") {
          const [lng, lat] = g.coordinates;
          const isEscale = p.point_type === "escale";
          if (isEscale) escales.push({ lat, lng, name: p.name });
          else intermediates.push({ lat, lng, name: p.name });
        }
      });
      // Intermediate waypoints — small muted dots (no tooltip, no popup — cleaner map)
      intermediates.forEach((w) => {
        L.circleMarker([w.lat, w.lng], {
          radius: 2.5,
          color: INTERMEDIATE_STROKE,
          weight: 1,
          fillColor: INTERMEDIATE_FILL,
          fillOpacity: 0.9,
          interactive: false,
          pane: "route",
        }).addTo(group);
      });
      // Escale waypoints — larger dots (no permanent label, popup on click only)
      escales.forEach((w) => {
        const m = L.circleMarker([w.lat, w.lng], {
          radius: 6,
          color: ESCALE_STROKE,
          weight: 2,
          fillColor: ESCALE_FILL,
          fillOpacity: 1,
          pane: "route",
        });
        m.bindPopup(
          () => `<div style="min-width:200px;">
            <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:rgb(var(--accent-rgb));text-transform:uppercase;letter-spacing:0.1em;">${tRef.current(
              "routeWaypointEscale",
            )}</div>
            <div style="font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:14px;color:#fff;line-height:1.3;margin-top:4px;">${
              w.name || ""
            }</div>
          </div>`,
          { ...POPUP_OPTS, maxWidth: 260 },
        );
        m.addTo(group);
      });
      routeLayerRef.current = group;
      group.addTo(map);
    })();
    // eslint-disable-next-line
  }, [t]);

  return routeLayerRef;
}
