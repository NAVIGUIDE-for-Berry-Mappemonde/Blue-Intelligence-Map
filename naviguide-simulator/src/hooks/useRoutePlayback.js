import { useCallback, useEffect, useRef, useState } from "react";
import { atlanticSpanNm, playheadOnPlay } from "../engine/routePlayhead.js";
import { airHopSeconds, nmPerSecond } from "../engine/playSpeeds.js";
import { edgeAtFilmNm, filmLength } from "../engine/filmCast.js";
import { dwellMsForProfile, shouldPauseAtStop, stepPlayback } from "../engine/stationDwell.js";

function playheadLength(flat) {
  return filmLength(flat) || flat?.totalNm || 0;
}

function rateAtPlayhead(flat, filmNm, sailRate, profile) {
  const edge = edgeAtFilmNm(flat, filmNm);
  if (edge?.jump) {
    const span = Math.max(1e-6, edge.filmSpan);
    return span / airHopSeconds(profile);
  }
  return sailRate;
}

function asStations(marks) {
  return (marks || []).map((m) => ({
    filmNm: m.filmNm ?? m.nm,
    nm: m.nm,
    name: m.name,
    kind: m.kind,
  }));
}

export function useRoutePlayback({ flat, marks, boatKnots, enabled, stopAuto = false }) {
  const [playing, setPlaying] = useState(false);
  const [profile, setProfile] = useState("normal");
  const [nm, setNm] = useState(0);
  const [jumpToken, setJumpToken] = useState(0);
  const [holdingStation, setHoldingStation] = useState(null);
  const nmRef = useRef(0);
  const lastTs = useRef(0);
  const emitAcc = useRef(0);
  const lastAir = useRef(false);
  const dwellLeftRef = useRef(0);
  const skipDwellRef = useRef(false);
  const marksRef = useRef(marks);
  marksRef.current = marks;
  const boatKnotsRef = useRef(boatKnots);
  boatKnotsRef.current = boatKnots;
  const stopAutoRef = useRef(stopAuto);
  stopAutoRef.current = stopAuto;

  const totalNm = playheadLength(flat);
  const atlanticNm = atlanticSpanNm(marks, flat?.totalNm || totalNm);
  const sailRate = nmPerSecond(profile, { boatKnots, atlanticNm });

  const clearHold = useCallback(() => {
    dwellLeftRef.current = 0;
    setHoldingStation(null);
  }, []);

  const seek = useCallback((nextNm, { play = false, jump = false } = {}) => {
    const total = playheadLength(flat);
    const clamped = Math.max(0, Math.min(total, Number(nextNm) || 0));
    nmRef.current = clamped;
    setNm(clamped);
    dwellLeftRef.current = 0;
    setHoldingStation(null);
    if (jump) {
      skipDwellRef.current = true;
      setJumpToken((n) => n + 1);
    }
    if (play) setPlaying(true);
  }, [flat]);

  const play = useCallback(() => setPlaying(true), []);
  const pause = useCallback(() => {
    setPlaying(false);
    dwellLeftRef.current = 0;
    setHoldingStation(null);
  }, []);
  const toggle = useCallback(() => {
    setPlaying((p) => {
      if (!p) {
        const total = playheadLength(flat);
        const next = playheadOnPlay(nmRef.current, total);
        if (next !== nmRef.current) {
          nmRef.current = next;
          setNm(next);
          dwellLeftRef.current = 0;
          setHoldingStation(null);
          skipDwellRef.current = true;
          setJumpToken((n) => n + 1);
        }
      }
      return !p;
    });
  }, [flat]);

  useEffect(() => {
    if (!enabled) {
      setPlaying(false);
      clearHold();
    }
  }, [enabled, clearHold]);

  useEffect(() => {
    const total = playheadLength(flat);
    if (nmRef.current > total) {
      nmRef.current = total;
      setNm(total);
    }
  }, [flat]);

  useEffect(() => {
    if (!enabled || !playing) {
      lastTs.current = 0;
      return undefined;
    }
    let raf = 0;
    const loop = (ts) => {
      if (!lastTs.current) lastTs.current = ts;
      const dt = Math.min(0.08, (ts - lastTs.current) / 1000);
      lastTs.current = ts;
      const total = playheadLength(flat);
      const liveRate = nmPerSecond(profile, {
        boatKnots: boatKnotsRef.current,
        atlanticNm,
      });
      const rate = rateAtPlayhead(flat, nmRef.current, liveRate, profile);
      const inAir = Boolean(edgeAtFilmNm(flat, nmRef.current)?.jump);
      if (inAir !== lastAir.current) {
        lastAir.current = inAir;
        setJumpToken((n) => n + 1);
      }
      const jump = skipDwellRef.current;
      skipDwellRef.current = false;
      const stepped = stepPlayback({
        filmNm: nmRef.current,
        dwellMsLeft: dwellLeftRef.current,
        deltaMs: dt * 1000,
        rate,
        stations: asStations(marksRef.current),
        maxFilmNm: total,
        dwellMs: stopAutoRef.current ? 0 : dwellMsForProfile(profile),
        jump,
      });
      dwellLeftRef.current = stepped.dwellMsLeft;
      nmRef.current = stepped.filmNm;
      if (shouldPauseAtStop(stopAutoRef.current, stepped.arrived)) {
        setPlaying(false);
        setNm(stepped.filmNm);
        setHoldingStation(stepped.arrived);
        return;
      }
      if (stepped.arrived) setHoldingStation(stepped.arrived);
      else if (!stepped.holding) setHoldingStation(null);
      emitAcc.current += dt;
      if (emitAcc.current >= 1 / 12 || stepped.filmNm >= total || stepped.arrived) {
        emitAcc.current = 0;
        setNm(stepped.filmNm);
      }
      if (stepped.filmNm >= total && !stepped.holding) {
        setPlaying(false);
        setNm(total);
        setHoldingStation(null);
        return;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [enabled, playing, profile, flat, atlanticNm]);

  return {
    nm,
    playing,
    profile,
    setProfile,
    play,
    pause,
    toggle,
    seek,
    jumpToken,
    atlanticNm,
    totalNm,
    rate: sailRate,
    sailTotalNm: flat?.totalNm || 0,
    holdingStation,
    holding: Boolean(holdingStation),
  };
}
