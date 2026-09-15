import { useEffect, useRef } from "react";
import L from "leaflet";
import { corridorForBoat } from "../utils/gribCorridor.js";
import { wrapLon } from "../utils/geo.js";
import {
  gribBarbSvg,
  gribDisplayPoints,
  waveHsColor,
  worldCopyLngs,
} from "../utils/gribSymbols.js";

function lonNearBox(lon, west, east) {
  const x = Number(lon);
  const w = Number(west);
  const e = Number(east);
  if (w <= e) return x >= w - 2 && x <= e + 2;
  return x >= w - 2 || x <= e + 2;
}

function sampleNearBox(s, south, north, west, east) {
  if (s.lat == null || s.lon == null) return false;
  if (s.lat < south - 1 || s.lat > north + 1) return false;
  const copies = worldCopyLngs(s.lon).concat(wrapLon(s.lon));
  return copies.some((lng) => lonNearBox(lng, west, east) || lonNearBox(lng, wrapLon(west), wrapLon(east)));
}

function cellKey(value) {
  return value == null ? null : Math.round(Number(value) * 20) / 20;
}

/** Barbules OMM + disques Hs en stencil. Jamais un rectangle de couloir. */
export function useGribCorridorLayer(mapRef, { grib, mapReady, visible, whenIso, lat, lon }) {
  const groupRef = useRef(null);
  const latCell = cellKey(lat);
  const lonCell = cellKey(lon == null ? null : wrapLon(lon));

  useEffect(() => {
    const map = mapRef.current;
    if (groupRef.current) {
      groupRef.current.remove();
      groupRef.current = null;
    }
    if (!map || !mapReady || !visible || grib?.status !== "ready") return undefined;
    const box = corridorForBoat(grib.bbox, latCell, lonCell);
    if (!box) return undefined;
    const [south, north, west, east] = box;

    const group = L.layerGroup().addTo(map);
    groupRef.current = group;

    const near = (grib.samples || []).filter((s) => sampleNearBox(s, south, north, west, east));
    const slice = gribDisplayPoints(near.length ? near : grib.samples, {
      lat: latCell,
      lon: lonCell,
      whenIso,
    });
    const pane = map.getPane("boat") ? "boat" : "overlayPane";
    for (const s of slice) {
      const baseLon = wrapLon(s.lon);
      for (const lng of worldCopyLngs(baseLon)) {
        if (s.hs != null) {
          L.circleMarker([s.lat, lng], {
            radius: 10,
            color: waveHsColor(s.hs),
            fillColor: waveHsColor(s.hs),
            fillOpacity: 0.38,
            weight: 0,
            pane,
            interactive: false,
          }).addTo(group);
        }
        if (s.windKnots == null) continue;
        L.marker([s.lat, lng], {
          icon: L.divIcon({
            className: "grib-barb",
            html: gribBarbSvg(s),
            iconSize: [36, 36],
            iconAnchor: [18, 18],
          }),
          pane,
          interactive: false,
          keyboard: false,
        }).addTo(group);
      }
    }
    return () => {
      group.remove();
      groupRef.current = null;
    };
  }, [mapRef, mapReady, visible, grib, whenIso, latCell, lonCell]);
}
