import { useEffect, useMemo, useRef, useState } from "react";
import { haversineNm, wrapLon } from "../utils/geo.js";
import {
  boatPositionFromCast,
  emptyDossier,
  mergeDossier,
  zeeEnterEvent,
} from "../engine/ici.js";
import { narrateIci } from "../engine/iciBriefing.js";

const API_URL = import.meta.env.VITE_API_URL ?? "";
const DEBOUNCE_MS = 800;
const MOVE_NM = 3;
const FETCH_MS = 40000;

/**
 * Fill the `ici()` bag around the boat and turn it into a story.
 * One step = one GET /ici. No chat, no Tavily.
 */
export function useIciDossier({
  enabled,
  cast,
  snappedPosition,
  polarMeta,
  jambe,
  lang = "fr",
}) {
  const [remote, setRemote] = useState(null);
  const lastFetchRef = useRef(null);
  const prevZeeRef = useRef(undefined);
  const abortRef = useRef(null);
  const timerRef = useRef(null);
  const boat = boatPositionFromCast(cast, snappedPosition);

  useEffect(() => {
    if (!enabled || !boat) {
      setRemote(null);
      lastFetchRef.current = null;
      prevZeeRef.current = undefined;
      abortRef.current?.abort();
      return undefined;
    }

    const lat = boat.lat;
    const lon = wrapLon(boat.lon);
    const last = lastFetchRef.current;
    if (last && haversineNm(last.lat, last.lon, lat, lon) < MOVE_NM) {
      return undefined;
    }

    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      const kill = setTimeout(() => ctrl.abort(), FETCH_MS);
      fetch(`${API_URL}/ici?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`, {
        signal: ctrl.signal,
      })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`ici ${r.status}`))))
        .then((data) => {
          const event = zeeEnterEvent(prevZeeRef.current, data?.zee);
          prevZeeRef.current = data?.zee?.mrgid ?? null;
          lastFetchRef.current = { lat, lon };
          setRemote({ ...data, event });
        })
        .catch(() => {
          if (ctrl.signal.aborted && lastFetchRef.current) return;
          if (ctrl.signal.aborted && !lastFetchRef.current) {
            setRemote({
              ...emptyDossier(lat, lon),
              sources: { zee: "error", bi: "unavailable" },
            });
            return;
          }
          setRemote({
            ...emptyDossier(lat, lon),
            sources: { zee: "error", bi: "unavailable" },
          });
        })
        .finally(() => {
          clearTimeout(kill);
        });
    }, DEBOUNCE_MS);

    return () => clearTimeout(timerRef.current);
  }, [enabled, boat?.lat, boat?.lon]);

  const dossier = useMemo(() => {
    if (!enabled || !boat || !remote) return null;
    return mergeDossier(remote, { polarMeta, jambe, event: remote.event });
  }, [enabled, boat, remote, polarMeta, jambe]);

  const briefing = useMemo(
    () => (dossier ? narrateIci(dossier, lang) : ""),
    [dossier, lang],
  );

  return { dossier, briefing, loading: Boolean(enabled && boat && !remote) };
}
