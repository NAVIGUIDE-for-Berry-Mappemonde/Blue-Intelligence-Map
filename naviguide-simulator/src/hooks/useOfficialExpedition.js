import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_T0_ISO, OFFICIAL_VOYAGE_ID, sampleClockAtTime } from "../engine/voyageClock.js";

const API = import.meta.env.VITE_API_URL ?? "";

/**
 * Voyage officiel unique. Pas de localStorage visiteur.
 * Position = horloge locale à maintenant (1 s = 1 s).
 * Dernier GRIB = overlay vent, jamais un nouveau trait, jamais de climatologie.
 */
export function useOfficialExpedition({
  enabled,
  points,
  marks,
  expeditionId,
  clock,
}) {
  const [meta, setMeta] = useState(null);
  const [serverClock, setServerClock] = useState(null);
  const [grib, setGrib] = useState(null);
  const [gribPending, setGribPending] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const putRef = useRef("");
  const clockRef = useRef(clock);
  clockRef.current = clock;

  useEffect(() => {
    if (!enabled) return undefined;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [enabled]);

  const putOfficial = useCallback(async () => {
    if (!points?.length) return null;
    const fp = `${points.length}|${points[0]?.lat}|${points[points.length - 1]?.lat}|${expeditionId || ""}`;
    if (putRef.current === fp && meta?.voyageId === OFFICIAL_VOYAGE_ID) return meta;
    const res = await fetch(`${API}/voyage/official`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        t0: DEFAULT_T0_ISO,
        expedition_id: expeditionId || "berry-mappemonde-2026",
        routeKind: "berry",
        follow: true,
        forecast: false,
        startAt: "la-rochelle",
        official: true,
        points: points.map((p) => ({
          lat: p.lat,
          lon: p.lon,
          cumNm: p.cumNm,
          filmCum: p.filmCum,
          jump: Boolean(p.jump),
          nonMaritime: Boolean(p.nonMaritime),
        })),
        marks: (marks || []).map((m) => ({
          name: m.name,
          nm: m.nm,
          filmNm: m.filmNm,
          lat: m.lat,
          lon: m.lon,
          index: m.index,
          flag: true,
        })),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return null;
    putRef.current = fp;
    setMeta(data);
    if (data.clock) setServerClock(data.clock);
    return data;
  }, [points, marks, expeditionId, meta]);

  useEffect(() => {
    if (!enabled || !points?.length) return undefined;
    let cancelled = false;
    const kick = () => {
      putOfficial().then((body) => {
        if (cancelled || !body) return;
        fetch(`${API}/voyage/official/clock`)
          .then((r) => (r.ok ? r.json() : null))
          .then((ck) => { if (ck && !cancelled) setServerClock(ck); })
          .catch(() => {});
      }).catch(() => {});
    };
    kick();
    const retry = setInterval(() => {
      if (!putRef.current) kick();
    }, 5000);
    return () => {
      cancelled = true;
      clearInterval(retry);
    };
  }, [enabled, points, putOfficial]);

  const refreshGrib = useCallback(async ({ force = false } = {}) => {
    const url = force ? `${API}/voyage/official/grib/refresh` : `${API}/voyage/official/grib`;
    const res = await fetch(url, force ? { method: "POST" } : undefined);
    const data = await res.json().catch(() => null);
    if (res.ok && data) setGrib(data);
    return data;
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    setGribPending(true);
    refreshGrib({ force: true }).catch(() => {}).finally(() => {
      if (!cancelled) setGribPending(false);
    });
    const id = setInterval(() => {
      refreshGrib().catch(() => {});
    }, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [enabled, refreshGrib, meta?.voyageId]);

  const live = useMemo(() => {
    if (!enabled || !clock) return null;
    const sample = sampleClockAtTime(clock, new Date(nowMs));
    if (!sample) return null;
    const wind = grib?.wind;
    if (grib?.status === "ready" && wind) {
      const models = (grib.products || [])
        .filter((p) => p.status === "ready")
        .map((p) => p.model);
      return {
        ...sample,
        kind: "forecast",
        model: models[0] || grib.model || wind.model || "GFS",
        waveModel: grib.waveModel || wind.waveModel || null,
        currentModel: grib.currentModel || wind.currentModel || null,
        windKnots: wind.windKnots,
        dirFromDeg: wind.dirFromDeg,
        pressHpa: wind.pressHpa,
        rainMm: wind.rainMm,
        hs: wind.hs,
        gribStatus: "ready",
        gribWarning: null,
      };
    }
    return {
      ...sample,
      kind: "absent",
      model: null,
      windKnots: null,
      dirFromDeg: null,
      gribStatus: grib?.status || "absent",
      gribWarning: "dernière prévision absente",
    };
  }, [enabled, clock, nowMs, grib]);

  return {
    voyageId: OFFICIAL_VOYAGE_ID,
    voyage: meta,
    clock: serverClock,
    live,
    grib,
    gribStatus: grib?.status === "ready"
      ? "ready"
      : (enabled ? (gribPending || !grib ? "pending" : "absent") : null),
    gribModel: (grib?.products || [])
      .filter((p) => p.status === "ready")
      .map((p) => p.model)
      .filter(Boolean)
      .join(" · ") || grib?.model || null,
    gribWarning: grib?.status === "ready" || gribPending || !grib
      ? null
      : (enabled ? "dernière prévision absente" : null),
    refreshGrib,
  };
}
