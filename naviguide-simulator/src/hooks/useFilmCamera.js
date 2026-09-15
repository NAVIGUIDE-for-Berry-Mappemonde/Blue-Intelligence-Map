import { useEffect, useRef } from "react";
import { haversineNm, unwrapLon } from "../utils/geo.js";
import { isAirPhase } from "../engine/filmCast.js";

const TELEPORT_NM = 80;

function zoomForRemaining(nm) {
  if (nm > 1800) return 3;
  if (nm > 500) return 4;
  if (nm > 120) return 5;
  if (nm > 30) return 6;
  return 7;
}

function unwrapPair(prev, lon) {
  return unwrapLon(prev, lon);
}

/** Follow the active actor, or frame the air hop to see Cayenne and Halifax. */
export function useFilmCamera({
  mapRef,
  mapReady,
  enabled,
  lat,
  lon,
  remainingNm,
  playing,
  jumpToken,
  phase,
  hopFrom,
  hopTo,
  resetKey = "",
}) {
  const lastFollow = useRef(0);
  const lastJump = useRef(0);
  const lastPos = useRef(null);
  const followLon = useRef(null);
  const lastPhase = useRef(null);
  const lastReset = useRef(resetKey);

  if (lastReset.current !== resetKey) {
    lastReset.current = resetKey;
    lastFollow.current = 0;
    lastJump.current = 0;
    lastPos.current = null;
    followLon.current = null;
    lastPhase.current = null;
  }

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !enabled || lat == null || lon == null) return;

    const lonCam = unwrapPair(followLon.current, lon);
    followLon.current = lonCam;
    const prev = lastPos.current;
    const movedNm = prev ? haversineNm(prev.lat, prev.lon, lat, lon) : 0;
    lastPos.current = { lat, lon };
    const z = zoomForRemaining(remainingNm);
    const tokenJump = jumpToken && jumpToken !== lastJump.current;
    if (tokenJump) lastJump.current = jumpToken;
    const phaseChanged = phase && phase !== lastPhase.current;
    if (phase) lastPhase.current = phase;

    if (isAirPhase(phase) && hopFrom && hopTo) {
      if (phaseChanged || tokenJump) {
        const lonA = unwrapPair(followLon.current, hopFrom.lon);
        const lonB = unwrapPair(lonA, hopTo.lon);
        followLon.current = lonB;
        map.fitBounds(
          [
            [hopFrom.lat, lonA],
            [hopTo.lat, lonB],
          ],
          { padding: [72, 96], maxZoom: 3.15, animate: true, duration: 0.9 },
        );
        lastFollow.current = Date.now();
        lastPos.current = null;
      }
      return;
    }

    const teleport = tokenJump || phaseChanged || movedNm >= TELEPORT_NM;
    if (teleport) {
      map.flyTo([lat, lonCam], z, { duration: movedNm >= TELEPORT_NM || phaseChanged ? 0.7 : 1.05 });
      lastFollow.current = Date.now();
      return;
    }

    if (!playing) return;
    const now = Date.now();
    if (now - lastFollow.current < 700) return;
    lastFollow.current = now;
    const cur = map.getZoom();
    const zoom = Math.abs(cur - z) >= 1.25 ? z : cur;
    map.setView([lat, lonCam], zoom, { animate: true, duration: 0.55 });
  }, [mapRef, mapReady, enabled, lat, lon, remainingNm, playing, jumpToken, phase, hopFrom?.lat, hopFrom?.lon, hopTo?.lat, hopTo?.lon, resetKey]);
}
