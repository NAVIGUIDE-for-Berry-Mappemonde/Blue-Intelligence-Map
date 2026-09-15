import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Redo2, Undo2, X } from "lucide-react";
import { Sidebar } from "./components/Sidebar.jsx";
import { ToolsSidebar } from "./components/ToolsSidebar.jsx";
import { LayerFichePopup } from "./components/LayerFichePopup.jsx";
import NotForNavModal from "./components/NotForNavModal.jsx";
import { readNotForNavAccepted, writeNotForNavAccepted } from "./utils/notForNav.js";
import { useCatamaranMarker } from "./components/CatamaranMarker.jsx";
import { usePlaneMarker } from "./components/PlaneMarker.jsx";
import { WindDirectionArrow } from "./components/map/WindDirectionArrow";
import { getCardinalDirection } from "./utils/getCardinalDirection";
import { useLang } from "./i18n/LangContext.jsx";
import { ITINERARY_POINTS } from "./constants/itineraryPoints";
import { SimulationFilmBar } from "./components/SimulationFilmBar.jsx";
import { ArrivalCard } from "./components/ArrivalCard.jsx";
import { RecomputeDialog } from "./components/RecomputeDialog.jsx";
import { useSimulatorMap } from "./hooks/useSimulatorMap.js";
import { useMarkerOffsets } from "./hooks/useMarkerOffsets.js";
import { useRoutePlayback } from "./hooks/useRoutePlayback.js";
import { useRouteWindProfile } from "./hooks/useRouteWindProfile.js";
import { useExpeditionSpeed } from "./hooks/useExpeditionSpeed.js";
import { useVoyageClock } from "./hooks/useVoyageClock.js";
import { useVirtualVessel } from "./hooks/useVirtualVessel.js";
import { useOfficialExpedition } from "./hooks/useOfficialExpedition.js";
import { useWakeLayer } from "./hooks/useWakeLayer.js";
import { useIciDossier } from "./hooks/useIciDossier.js";
import { useFilmCamera } from "./hooks/useFilmCamera.js";
import { useAirHopLine } from "./hooks/useAirHopLine.js";
import { useRouteLayer } from "./layers/useRouteLayer.js";
import { useAltRouteLayer } from "./layers/useAltRouteLayer.js";
import { useToggleLayers } from "./layers/useToggleLayers.js";
import {
  flattenRoute,
  interpolateAtNm,
  nearestNm,
  mapEscalesOnRoute,
  nextEscaleNm,
  prevEscaleNm,
  filmLegContext,
} from "./engine/routePlayhead.js";
import { detectAirEpisodes, interpolateCast, isAirPhase, mergeEpisodeMarks, sailNmToFilmNm } from "./engine/filmCast.js";
import { expeditionBoatKnots } from "./engine/playSpeeds.js";
import { formatSeaClock } from "./engine/seaTime.js";
import { nextStationAfter } from "./engine/stationDwell.js";
import {
  DEFAULT_START_AT,
  DEFAULT_T0_ISO,
  etaHoursToFilmNm,
  formatCivilDate,
  formatFilmClockLine,
  formatMonthName,
  lookupVoyageClock,
} from "./engine/voyageClock.js";
import { VIEW_SIMULATION, VIEW_SUIVRE } from "./constants/viewMode.js";
import { isRouteReady } from "./utils/routeReady.js";
import { isSceneReady, playheadAligned } from "./utils/sceneGate.js";
import { useGribCorridorLayer } from "./layers/useGribCorridorLayer.js";
import { summarizeRoute, featuresToSegments } from "./utils/geo.js";
import { waypointsFromCollection } from "./utils/waypointsFromCollection.js";
import { buildLocalCustomBriefing } from "./utils/customRouteBriefing.js";
import {
  activeSimulationSegments,
  activeSimulationStops,
} from "./utils/simulationRoute.js";
import {
  SEGMENT_BATCH_SIZE,
  buildBerryLegs,
  coordsFromRoutePayload,
  isNonMaritimeLeg,
  orientCoords,
} from "./utils/berryLegs.js";
import { loadOfficialBerryRoute } from "./utils/routeFromOfficial.js";
import L from "leaflet";

const API_URL = import.meta.env.VITE_API_URL ?? "";
const ORCHESTRATOR_URL = import.meta.env.VITE_ORCHESTRATOR_URL;
const PLAN_CACHE_TTL = 24 * 60 * 60 * 1000;

function planCacheKey(lang) { return `naviguide_sim_plan_v1_${lang}`; }
function getCachedPlan(lang) {
  try {
    const raw = localStorage.getItem(planCacheKey(lang));
    if (!raw) return null;
    const { data, ts } = JSON.parse(raw);
    if (Date.now() - ts > PLAN_CACHE_TTL) { localStorage.removeItem(planCacheKey(lang)); return null; }
    return data;
  } catch { return null; }
}
function setCachedPlan(lang, data) {
  try { localStorage.setItem(planCacheKey(lang), JSON.stringify({ data, ts: Date.now() })); } catch { /* quota */ }
}

function pointToSegmentPx(map, lat, lon, coords) {
  const p = map.latLngToLayerPoint([lat, lon]);
  let best = Infinity;
  for (let i = 0; i < coords.length - 1; i++) {
    const [lon1, lat1] = coords[i];
    const [lon2, lat2] = coords[i + 1];
    const a = map.latLngToLayerPoint([lat1, lon1]);
    const b = map.latLngToLayerPoint([lat2, lon2]);
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const lenSq = dx * dx + dy * dy;
    const t = lenSq ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq)) : 0;
    const dist = Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
    if (dist < best) best = dist;
  }
  return best;
}

export default function App() {
  const { lang, t } = useLang();
  const containerRef = useRef(null);
  const [isLightMode, setIsLightMode] = useState(false);
  const { mapRef, mapReady } = useSimulatorMap(containerRef, isLightMode);

  const [segments, setSegments] = useState([]);
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [segProgress, setSegProgress] = useState({ done: 0, total: 0 });
  const [officialFallback, setOfficialFallback] = useState(false);

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [toolsOpen, setToolsOpen] = useState(true);
  const [expeditionPlan, setExpeditionPlan] = useState(null);
  const [polarData, setPolarData] = useState(null);
  const [briefingLoading, setBriefingLoading] = useState(false);

  const [view, setView] = useState(VIEW_SUIVRE);
  const [cinemaMode, setCinemaMode] = useState(false);
  const [hideFilmBar, setHideFilmBar] = useState(false);
  const [stopAuto, setStopAuto] = useState(false);
  const [cameraFollow, setCameraFollow] = useState(false);
  const [cinemaRecapture, setCinemaRecapture] = useState(0);
  const [userPreview, setUserPreview] = useState(false);
  const isSuivre = view === VIEW_SUIVRE;
  const isSimulation = view === VIEW_SIMULATION;
  const [voyageFlat, setVoyageFlat] = useState(null);
  const [cameraPlaced, setCameraPlaced] = useState(false);
  const [arrivalBanner, setArrivalBanner] = useState(null);
  const [liveKnots, setLiveKnots] = useState(null);
  const cinemaSavedRef = useRef({ sidebar: true, tools: true });
  const prevPlayheadRef = useRef(0);
  const lastArrivalKeyRef = useRef("");
  const [customRoute, setCustomRoute] = useState(null);
  const [routeKind, setRouteKind] = useState("berry");
  const routeKindRef = useRef("berry");
  const berryFetchIdRef = useRef(0);
  const customFetchIdRef = useRef(0);

  const [drawingMode, setDrawingMode] = useState(false);
  const [drawnPoints, setDrawnPoints] = useState([]);
  const [drawnSegments, setDrawnSegments] = useState([]);
  const [drawingLoading, setDrawingLoading] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const drawnPointsRef = useRef([]);
  const drawnSegmentsRef = useRef([]);
  const undonePointsRef = useRef([]);
  const undoneSegmentsRef = useRef([]);
  const fetchIdRef = useRef(0);

  const [layerPopup, setLayerPopup] = useState(null);
  const [hoveredPoint, setHoveredPoint] = useState(null);
  const [clipboardToast, setClipboardToast] = useState(null);
  const [selectedSatellite, setSelectedSatellite] = useState(null);
  const [satelliteLoading, setSatelliteLoading] = useState(false);
  const [satelliteTab, setSatelliteTab] = useState("wind");
  const [pointInfoName, setPointInfoName] = useState("");
  const [pointInfoFlags, setPointInfoFlags] = useState([null, null]);

  const onFeature = useCallback((fiche) => {
    setSelectedSatellite(null);
    setLayerPopup(fiche);
  }, []);
  const [notForNavOk, setNotForNavOk] = useState(() => readNotForNavAccepted());
  const [notForNavOpen, setNotForNavOpen] = useState(false);
  const pendingLayerRef = useRef(null);
  const gateRef = useRef({
    allowed: notForNavOk,
    onNeed: (kind) => {
      pendingLayerRef.current = kind;
      setNotForNavOpen(true);
    },
  });
  gateRef.current.allowed = notForNavOk;
  const maritimeLayers = useToggleLayers(mapRef, onFeature, mapReady, gateRef);

  const routeForView = isSuivre ? null : customRoute;
  const routeReady = isRouteReady(segProgress) || (officialFallback && segments.length > 0);
  const activeStops = useMemo(() => activeSimulationStops(routeForView, points.length ? points : ITINERARY_POINTS), [routeForView, points]);
  const activeSegments = useMemo(() => activeSimulationSegments(routeForView, segments), [routeForView, segments]);
  const baseFlat = useMemo(() => flattenRoute(activeSegments), [activeSegments]);
  const flatRoute = voyageFlat || baseFlat;
  const escaleMarks = useMemo(
    () => mergeEpisodeMarks(mapEscalesOnRoute(activeStops, flatRoute), flatRoute, activeStops),
    [activeStops, flatRoute],
  );
  const cruiseKnots = useMemo(() => expeditionBoatKnots(polarData), [polarData]);
  const voyage = useVoyageClock({
    flat: flatRoute,
    marks: escaleMarks,
    polarRaw: polarData?.raw || null,
    enabled: Boolean(flatRoute.points?.length) && routeReady,
    stops: activeStops,
  });
  const official = useOfficialExpedition({
    enabled: isSuivre,
    points: routeReady ? flatRoute.points : undefined,
    marks: routeReady ? escaleMarks : [],
    expeditionId: polarData?.expedition_id,
    clock: voyage.clock,
  });
  const vessel = useVirtualVessel({
    enabled: isSimulation && routeReady,
    forecast: false,
    follow: false,
    t0: voyage.t0,
    startAt: voyage.startAt,
    expeditionId: polarData?.expedition_id,
    routeKind,
    points: flatRoute.points,
    marks: escaleMarks,
  });
  const officialClock = voyage.clock || official.clock;
  const boatKnots = liveKnots > 0 ? liveKnots : cruiseKnots;

  const playback = useRoutePlayback({
    flat: flatRoute,
    marks: escaleMarks,
    boatKnots,
    enabled: routeReady,
    stopAuto: isSimulation && stopAuto,
  });
  const live = isSuivre ? official.live : vessel.live;
  const previewing = Boolean(isSuivre && live && userPreview);
  const playheadReady = playheadAligned({
    isSuivre,
    previewing,
    playbackNm: playback.nm,
    liveFilmNm: live?.filmNm,
  });
  const sceneReady = isSceneReady({
    routeReady,
    hasRoute: Boolean(flatRoute.points?.length),
    cameraPlaced,
    playheadReady,
    isSuivre,
    hasLive: Boolean(live),
    previewing,
  });
  const clockSample = useMemo(() => {
    if (isSuivre && live && !previewing) return live;
    return lookupVoyageClock(officialClock, playback.nm, { atQuay: playback.holding });
  }, [isSuivre, live, previewing, officialClock, playback.nm, playback.holding]);
  const windProfile = useRouteWindProfile({
    flat: flatRoute,
    marks: escaleMarks,
    polarData,
    cruiseKnots,
    enabled: Boolean(officialClock),
    clock: officialClock,
  });

  const cast = useMemo(
    () => interpolateCast(flatRoute, playback.nm, { stops: activeStops }),
    [flatRoute, playback.nm, activeStops],
  );
  const sample = useMemo(() => {
    if (!cast) return interpolateAtNm(flatRoute, playback.nm);
    const actor = cast.vehicle === "side" ? cast.side : cast.main;
    return {
      lat: actor.lat,
      lon: actor.lon,
      bearing: actor.bearing,
      nm: cast.sailNm,
      jump: isAirPhase(cast.phase),
    };
  }, [cast, flatRoute, playback.nm]);

  const expeditionSpeed = useExpeditionSpeed({
    polarData,
    sample: cast?.vehicle === "plane" ? cast.main : sample,
    profile: playback.profile,
    playing: playback.playing && cast?.vehicle !== "plane",
    onLiveKnots: setLiveKnots,
    windSeries: windProfile.series,
    filmNm: playback.nm,
    clockSample,
    clockReady: Boolean(officialClock),
  });
  useWakeLayer(mapRef, {
    flat: flatRoute,
    sailNm: isSuivre && official.live && !previewing
      ? (official.live.sailNm ?? 0)
      : (cast?.sailNm ?? 0),
    enabled: sceneReady && !drawingMode && !customRoute,
    mapReady,
  });

  const legContext = useMemo(() => {
    if (!cast) return null;
    return filmLegContext({
      marks: escaleMarks,
      nm: cast.sailNm,
      sample,
      totalNm: playback.sailTotalNm || flatRoute.totalNm,
      boatKnots: expeditionSpeed.knots,
      cast,
    });
  }, [cast, sample, escaleMarks, playback.sailTotalNm, flatRoute.totalNm, expeditionSpeed.knots]);

  const clockEtaHours = useMemo(() => {
    if (!officialClock || !legContext || legContext.finished || (legContext.nmRemainingToStop ?? 0) < 0.5) {
      return 0;
    }
    const destNm = legContext.chapter?.to?.filmNm ?? legContext.chapter?.to?.nm;
    if (destNm == null) return legContext.etaHours;
    return etaHoursToFilmNm(officialClock, playback.nm, destNm, { atQuay: playback.holding })
      ?? legContext.etaHours;
  }, [officialClock, legContext, playback.nm, playback.holding]);

  const hudLeg = useMemo(() => {
    if (!legContext) return null;
    const local = Number(clockSample?.speedKnots);
    const sailing = clockSample
      && (clockSample.vehicle === "main" || clockSample.vehicle === "side")
      && Number.isFinite(local);
    return {
      ...legContext,
      etaHours: officialClock ? clockEtaHours : legContext.etaHours,
      speedKnots: sailing ? Math.round(local * 10) / 10 : (officialClock ? null : legContext.speedKnots),
        kind: clockSample?.kind === "forecast"
          ? "forecast"
          : (isSuivre ? "absent" : (clockSample?.kind || (officialClock ? "climatology" : legContext.kind))),
    };
  }, [legContext, clockSample, officialClock, clockEtaHours, isSuivre]);

  const jambe = useMemo(() => {
    if (!hudLeg) return null;
    return {
      fromStop: hudLeg.fromStop,
      toStop: hudLeg.toStop,
      speedKnots: hudLeg.speedKnots,
      etaHours: hudLeg.etaHours,
      remainingNm: hudLeg.nmRemainingToStop ?? hudLeg.remainingNm,
      phase: hudLeg.phase,
      vehicle: hudLeg.vehicle,
    };
  }, [hudLeg]);

  const legendMarks = useMemo(() => {
    const clockMarks = officialClock?.marks || [];
    return escaleMarks.map((m) => {
      const film = m.filmNm ?? m.nm;
      const hit = clockMarks.find((c) => (
        Math.abs((c.filmNm ?? c.nm) - film) < 0.6 && (!m.name || c.name === m.name)
      )) || clockMarks.find((c) => c.name === m.name);
      return hit ? { ...m, iso: hit.iso, holdHours: hit.holdHours } : m;
    });
  }, [escaleMarks, officialClock]);

  const civilDate = formatCivilDate(clockSample?.iso, lang);
  const monthLabel = clockSample?.month
    ? formatMonthName(clockSample.month, lang)
    : "";
  const climatologyLabel = clockSample?.kind === "forecast"
    ? t("voyageKindForecast", {
      model: clockSample.model || official.gribModel || vessel.voyage?.forecastModel || "GFS",
      lead: clockSample.leadHours != null ? Math.round(clockSample.leadHours) : "—",
    })
    : isSuivre
      ? ""
      : officialClock && monthLabel
        ? t("voyageKindClimatology", { month: monthLabel })
        : "";
  const quayDays = clockSample?.holdHours > 0
    ? Math.round(clockSample.holdHours / 24)
    : 0;
  const atQuay = Boolean(clockSample?.atQuay && quayDays > 0);
  const clockLine = officialClock?.vertices?.length && clockSample
    ? formatFilmClockLine({
      sailNm: isSuivre && !previewing
        ? (clockSample.sailNm ?? cast?.sailNm)
        : (cast?.sailNm ?? clockSample.sailNm),
      seaHours: clockSample.seaHours,
      iso: clockSample.iso,
      lang,
    })
    : "";

  useEffect(() => {
    if (clockSample?.speedKnots > 0) setLiveKnots(clockSample.speedKnots);
  }, [clockSample?.speedKnots]);

  useEffect(() => {
    if (isSuivre) {
      setVoyageFlat(null);
      return;
    }
    if (vessel.voyage?.points?.length && vessel.voyage.routeRev > 0) {
      const pts = vessel.voyage.points;
      const last = pts[pts.length - 1];
      setVoyageFlat({
        points: pts,
        totalNm: last?.cumNm || 0,
        totalFilmNm: last?.filmCum || last?.cumNm || 0,
        episodes: detectAirEpisodes(pts),
      });
    }
  }, [isSuivre, vessel.voyage?.routeRev, vessel.voyage?.points]);

  const goLive = useCallback(() => {
    if (!live) return;
    setUserPreview(false);
    playback.pause();
    playback.seek(Number(live.filmNm) || 0, { jump: true });
  }, [live, playback.pause, playback.seek]);

  useEffect(() => {
    if (isSuivre) setUserPreview(false);
  }, [isSuivre]);

  const livePrimedRef = useRef(false);
  useEffect(() => {
    if (!isSuivre) {
      livePrimedRef.current = false;
      return;
    }
    if (!routeReady || !live || userPreview) return;
    const target = Number(live.filmNm) || 0;
    if (Math.abs(playback.nm - target) > 2) {
      playback.seek(target, { jump: false });
    }
    livePrimedRef.current = true;
  }, [routeReady, isSuivre, live?.filmNm, userPreview, playback.nm, playback.seek]);

  const simPrimedRef = useRef(false);
  useEffect(() => {
    if (!isSimulation) {
      simPrimedRef.current = false;
      return;
    }
    if (!routeReady || simPrimedRef.current) return;
    simPrimedRef.current = true;
    voyage.setStartAt("saint-maur");
    playback.setProfile("normal");
    playback.pause();
    playback.seek(0, { jump: true });
  }, [isSimulation, routeReady, voyage.setStartAt, playback.pause, playback.seek, playback.setProfile]);

  const canRecompute = Boolean(
    isSimulation
    && cast?.vehicle === "main"
    && vessel.voyage?.voyageId,
  );

  const iciPack = useIciDossier({
    enabled: Boolean(cast),
    cast,
    snappedPosition: legContext?.snappedPosition,
    polarMeta: polarData,
    jambe,
    lang,
  });

  const playheadNmRef = useRef(0);
  playheadNmRef.current = playback.nm;

  const handleSimNext = useCallback(() => {
    lastArrivalKeyRef.current = "";
    setArrivalBanner(null);
    if (isSuivre) setUserPreview(true);
    playback.pause();
    playback.seek(nextEscaleNm(escaleMarks, playheadNmRef.current), { jump: true });
  }, [playback.pause, playback.seek, escaleMarks, isSuivre]);

  const handleSimPrev = useCallback(() => {
    lastArrivalKeyRef.current = "";
    setArrivalBanner(null);
    if (isSuivre) setUserPreview(true);
    playback.pause();
    playback.seek(prevEscaleNm(escaleMarks, playheadNmRef.current), { jump: true });
  }, [playback.pause, playback.seek, escaleMarks, isSuivre]);

  const handleCatamaranDrag = useCallback((pos) => {
    playback.pause();
    playback.seek(sailNmToFilmNm(flatRoute, nearestNm(flatRoute, pos.lat, pos.lon)));
  }, [playback.pause, playback.seek, flatRoute]);

  const recaptureBoat = useCallback(() => {
    setCameraFollow(true);
    setCinemaRecapture((n) => n + 1);
  }, []);

  const leaveCinema = useCallback(() => {
    setSidebarOpen(cinemaSavedRef.current.sidebar);
    setToolsOpen(cinemaSavedRef.current.tools);
    setCinemaMode(false);
    setHideFilmBar(false);
    setCameraFollow(false);
  }, []);

  const toggleCinema = useCallback(() => {
    if (!cinemaMode) {
      cinemaSavedRef.current = { sidebar: sidebarOpen, tools: toolsOpen };
      setSidebarOpen(false);
      setToolsOpen(false);
      setCinemaMode(true);
      recaptureBoat();
      return;
    }
    if (!cameraFollow) {
      recaptureBoat();
      return;
    }
    leaveCinema();
  }, [cinemaMode, cameraFollow, sidebarOpen, toolsOpen, recaptureBoat, leaveCinema]);

  const selectView = useCallback((next) => {
    setView(next);
    setArrivalBanner(null);
    lastArrivalKeyRef.current = "";
    if (next === VIEW_SUIVRE) {
      voyage.setT0(DEFAULT_T0_ISO);
      voyage.setStartAt(DEFAULT_START_AT);
      playback.pause();
      setUserPreview(false);
    } else {
      voyage.setStartAt("saint-maur");
      playback.setProfile("normal");
      playback.pause();
      playback.seek(0, { jump: true });
    }
  }, [voyage.setT0, voyage.setStartAt, playback.pause, playback.seek, playback.setProfile]);

  useEffect(() => {
    if (isSuivre) {
      voyage.setT0(DEFAULT_T0_ISO);
      voyage.setStartAt(DEFAULT_START_AT);
    }
  }, [isSuivre, voyage.setT0, voyage.setStartAt]);

  useEffect(() => {
    if (isSuivre) playback.setProfile("real");
  }, [isSuivre, playback.setProfile]);

  const placedRef = useRef(false);
  const ignoreUserNavRef = useRef(false);
  const ignoreUserNavTimer = useRef(0);
  const armProgrammaticNav = useCallback(() => {
    ignoreUserNavRef.current = true;
    window.clearTimeout(ignoreUserNavTimer.current);
    ignoreUserNavTimer.current = window.setTimeout(() => {
      ignoreUserNavRef.current = false;
    }, 120);
  }, []);
  useEffect(() => {
    placedRef.current = false;
  }, [view]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !routeReady || !flatRoute.points?.length) {
      setCameraPlaced(false);
      return;
    }
    if (placedRef.current) {
      setCameraPlaced(true);
      return;
    }
    if (isSuivre) {
      if (!live) {
        setCameraPlaced(false);
        return;
      }
      armProgrammaticNav();
      map.setView([live.lat, live.lon], 6.5, { animate: false });
      placedRef.current = true;
      setCameraPlaced(true);
      return;
    }
    const start = flatRoute.points[0];
    armProgrammaticNav();
    map.setView([start.lat, start.lon], 8, { animate: false });
    placedRef.current = true;
    setCameraPlaced(true);
  }, [routeReady, isSuivre, live?.lat, live?.lon, mapReady, mapRef, flatRoute.points, view, armProgrammaticNav]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return undefined;
    const onUserNav = () => {
      if (ignoreUserNavRef.current) return;
      map.stop();
      setCameraFollow(false);
    };
    map.on("zoomstart", onUserNav);
    map.on("dragstart", onUserNav);
    return () => {
      map.off("zoomstart", onUserNav);
      map.off("dragstart", onUserNav);
    };
  }, [mapRef, mapReady]);

  useEffect(() => {
    if (!isSimulation) return;
    playback.pause();
    playback.seek(0);
    prevPlayheadRef.current = 0;
    lastArrivalKeyRef.current = "";
    setArrivalBanner(null);
  }, [customRoute]);

  useEffect(() => {
    const prev = prevPlayheadRef.current;
    const cur = playback.nm;
    prevPlayheadRef.current = cur;
    if (Math.abs(cur - prev) > 8) {
      lastArrivalKeyRef.current = "";
      const landed = escaleMarks.find((m) => {
        const at = m.filmNm ?? m.nm;
        return at > 0.5 && Math.abs(cur - at) <= 0.8;
      });
      if (!landed) {
        setArrivalBanner(null);
        return undefined;
      }
      const landKey = `${landed.name}-${Math.round(landed.filmNm ?? landed.nm)}`;
      lastArrivalKeyRef.current = landKey;
      setArrivalBanner(landed);
      const timer = setTimeout(() => setArrivalBanner(null), 8000);
      return () => clearTimeout(timer);
    }
    if (cur + 2 < prev) {
      lastArrivalKeyRef.current = "";
      setArrivalBanner(null);
      return undefined;
    }
    const hit = escaleMarks.find((m) => {
      const at = m.filmNm ?? m.nm;
      return at > 0.5 && prev < at && cur >= at;
    });
    if (!hit) return undefined;
    const key = `${hit.name}-${Math.round(hit.filmNm ?? hit.nm)}`;
    if (lastArrivalKeyRef.current === key) return undefined;
    lastArrivalKeyRef.current = key;
    setArrivalBanner(hit);
    const timer = setTimeout(() => setArrivalBanner(null), 8000);
    return () => clearTimeout(timer);
  }, [playback.nm, escaleMarks]);

  useEffect(() => {
    const onKey = (e) => {
      if (e.target?.closest?.("input, textarea, select, [contenteditable]")) return;
      if (e.target?.closest?.("button") && e.code === "Space") return;
      if (e.code === "Space") {
        e.preventDefault();
        playback.toggle();
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        handleSimNext();
      } else if (e.code === "ArrowLeft") {
        e.preventDefault();
        handleSimPrev();
      } else if (e.code === "KeyC") {
        e.preventDefault();
        toggleCinema();
      } else if (e.code === "KeyL") {
        e.preventDefault();
        goLive();
      } else if (e.code === "Escape" && cinemaMode) {
        e.preventDefault();
        leaveCinema();
      } else if (e.code === "Digit1") {
        playback.setProfile("real");
      } else if (e.code === "Digit2") {
        playback.setProfile("read");
      } else if (e.code === "Digit3") {
        playback.setProfile("normal");
      } else if (e.code === "Digit4") {
        playback.setProfile("fast");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cinemaMode, playback.toggle, playback.setProfile, handleSimNext, handleSimPrev, toggleCinema, leaveCinema, goLive]);

  useFilmCamera({
    mapRef,
    mapReady,
    enabled: sceneReady && cameraFollow && Boolean(cast?.follow || (isSuivre && live)),
    lat: isSuivre && live && !previewing ? live.lat : cast?.follow?.lat,
    lon: isSuivre && live && !previewing ? live.lon : cast?.follow?.lon,
    remainingNm: legContext?.remainingNm ?? playback.sailTotalNm,
    playing: cameraFollow && (isSuivre && !previewing ? true : playback.playing),
    jumpToken: isSuivre && !previewing ? 0 : playback.jumpToken,
    phase: cast?.phase,
    hopFrom: cast?.hopFrom,
    hopTo: cast?.hopTo,
    resetKey: `${view}-${sceneReady ? "ready" : "load"}-${cinemaRecapture}`,
    follow: cameraFollow,
    recaptureToken: cinemaRecapture,
    onProgrammaticMove: armProgrammaticNav,
  });

  useAirHopLine(mapRef, {
    mapReady,
    visible: isAirPhase(cast?.phase),
    from: cast?.hopFrom,
    to: cast?.hopTo,
  });

  useCatamaranMarker(mapRef, {
    visible: sceneReady && isSimulation && Boolean(cast?.main),
    lat: cast?.main?.lat,
    lon: cast?.main?.lon,
    bearing: cast?.main?.bearing || 0,
    onDrag: handleCatamaranDrag,
    onDragStart: playback.pause,
    mapReady,
  });

  useCatamaranMarker(mapRef, {
    visible: sceneReady && isSuivre && Boolean(live) && cast?.vehicle !== "plane",
    lat: live?.lat,
    lon: live?.lon,
    bearing: live?.bearing || 0,
    onDrag: undefined,
    onDragStart: undefined,
    mapReady,
    draggable: false,
    className: "catamaran-divicon catamaran-divicon--live",
  });

  useCatamaranMarker(mapRef, {
    visible: sceneReady && isSuivre && previewing && Boolean(cast?.main),
    lat: cast?.main?.lat,
    lon: cast?.main?.lon,
    bearing: cast?.main?.bearing || 0,
    onDrag: undefined,
    onDragStart: undefined,
    mapReady,
    draggable: false,
    className: "catamaran-divicon catamaran-divicon--ghost",
  });

  useAltRouteLayer(mapRef, { draft: vessel.draft, mapReady });

  useCatamaranMarker(mapRef, {
    visible: sceneReady && Boolean(cast?.side?.visible),
    lat: cast?.side?.lat,
    lon: cast?.side?.lon,
    bearing: cast?.side?.bearing || 0,
    onDrag: undefined,
    onDragStart: undefined,
    mapReady,
    draggable: false,
    className: "catamaran-divicon catamaran-divicon--side",
  });

  usePlaneMarker(mapRef, {
    visible: sceneReady && Boolean(cast?.plane?.visible),
    lat: cast?.plane?.lat,
    lon: cast?.plane?.lon,
    bearing: cast?.plane?.bearing || 0,
    mapReady,
  });

  const routeCoords = useMemo(
    () => segments.filter((s) => !s.nonMaritime).flatMap((s) => s.coords || []),
    [segments],
  );
  const markerOffsets = useMarkerOffsets(points, mapRef, routeCoords);

  useRouteLayer(mapRef, {
    segments: sceneReady ? segments : [],
    customRoute: sceneReady ? customRoute : null,
    drawingMode,
    drawnSegments,
    mapReady,
    visible: sceneReady || drawingMode,
    hideMaritime: sceneReady && !customRoute && !drawingMode,
  });
  useGribCorridorLayer(mapRef, {
    grib: official.grib,
    mapReady,
    visible: isSuivre && official.gribStatus === "ready",
    whenIso: clockSample?.iso,
    lat: isSuivre ? live?.lat : null,
    lon: isSuivre ? live?.lon : null,
  });

  const applyBerryBriefing = useCallback(() => {
    setExpeditionPlan(getCachedPlan(lang) || { executive_briefing: t("berryLocalBriefing") });
    setBriefingLoading(false);
  }, [lang, t]);

  const handleRouteSwitchToBerry = () => {
    customFetchIdRef.current += 1;
    routeKindRef.current = "berry";
    setCustomRoute(null);
    setRouteKind("berry");
    setVoyageFlat(null);
    applyBerryBriefing();
  };

  const fetchCustomPlan = useCallback((geojson) => {
    const applyFallback = () => setExpeditionPlan(buildLocalCustomBriefing(geojson, lang));
    setExpeditionPlan(null);
    const wps = waypointsFromCollection(geojson);
    const hasLine = (geojson?.features || []).some((f) => f?.geometry?.type === "LineString" && f.geometry.coordinates?.length >= 2);
    if (wps.length < 2 && !hasLine) { setBriefingLoading(false); applyFallback(); return; }
    const requestId = ++customFetchIdRef.current;
    setBriefingLoading(true);
    const finish = (plan) => {
      if (customFetchIdRef.current !== requestId || routeKindRef.current !== "custom") return;
      setExpeditionPlan(plan);
      setBriefingLoading(false);
    };
    if (!ORCHESTRATOR_URL) { finish(buildLocalCustomBriefing(geojson, lang)); return; }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    fetch(`${ORCHESTRATOR_URL}/api/v1/expedition/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: lang, waypoints: wps }),
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`plan ${r.status}`))))
      .then((data) => finish(data?.expedition_plan?.executive_briefing ? data.expedition_plan : buildLocalCustomBriefing(geojson, lang)))
      .catch(() => finish(buildLocalCustomBriefing(geojson, lang)))
      .finally(() => clearTimeout(timer));
  }, [lang]);

  const handleCustomRoute = (geojson) => {
    berryFetchIdRef.current += 1;
    routeKindRef.current = "custom";
    setView(VIEW_SIMULATION);
    setCustomRoute(geojson);
    setRouteKind("custom");
    setVoyageFlat(null);
    setBriefingLoading(true);
    fetchCustomPlan(geojson);
  };

  const _resetDrawState = () => {
    setDrawnPoints([]);
    setDrawnSegments([]);
    setCanRedo(false);
    drawnPointsRef.current = [];
    drawnSegmentsRef.current = [];
    undonePointsRef.current = [];
    undoneSegmentsRef.current = [];
    fetchIdRef.current = 0;
  };

  const handleDrawStart = () => {
    playback.pause();
    setCinemaMode(false);
    setView(VIEW_SIMULATION);
    setArrivalBanner(null);
    setDrawingMode(true);
    _resetDrawState();
    berryFetchIdRef.current += 1;
    setExpeditionPlan(null);
    setBriefingLoading(false);
  };

  const handleDrawFinish = () => {
    const lineFeatures = drawnSegmentsRef.current.filter((s) => s.coords?.length > 0).map((s) => ({
      type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: s.coords },
    }));
    const pointFeatures = drawnPointsRef.current.map((p, i) => ({
      type: "Feature",
      properties: { name: p.name || `Point ${i + 1}`, flags: p.flags || [], naviguide_type: "drawn_waypoint" },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    }));
    setDrawingMode(false);
    return { type: "FeatureCollection", features: [...lineFeatures, ...pointFeatures] };
  };

  const handleDrawContinue = () => {
    playback.pause();
    setCinemaMode(false);
    setView(VIEW_SIMULATION);
    setArrivalBanner(null);
    setDrawingMode(true);
    setExpeditionPlan(null);
    setBriefingLoading(false);
  };

  const handleCustomDelete = () => {
    customFetchIdRef.current += 1;
    routeKindRef.current = "berry";
    setCustomRoute(null);
    setRouteKind("berry");
    setVoyageFlat(null);
    _resetDrawState();
    applyBerryBriefing();
  };

  const fetchDrawnSegment = async (from, to) => {
    const myFetchId = ++fetchIdRef.current;
    setDrawingLoading(true);
    try {
      const params = new URLSearchParams({ start_lat: from.lat, start_lon: from.lon, end_lat: to.lat, end_lon: to.lon });
      const res = await fetch(`${API_URL}/route?${params}`);
      const data = await res.json();
      let coords = coordsFromRoutePayload(data);
      let failed = false;
      if (!coords.length) {
        coords = [[from.lon, from.lat], [to.lon, to.lat]];
        failed = true;
      }
      if (fetchIdRef.current === myFetchId) {
        const updated = [...drawnSegmentsRef.current, { coords, failed }];
        drawnSegmentsRef.current = updated;
        setDrawnSegments([...updated]);
      }
    } catch {
      if (fetchIdRef.current === myFetchId) {
        const updated = [...drawnSegmentsRef.current, { coords: [[from.lon, from.lat], [to.lon, to.lat]], failed: true }];
        drawnSegmentsRef.current = updated;
        setDrawnSegments([...updated]);
      }
    } finally {
      if (fetchIdRef.current === myFetchId) setDrawingLoading(false);
    }
  };

  const handleDrawingClick = (lat, lon) => {
    const newPoint = { lat, lon };
    const updated = [...drawnPointsRef.current, newPoint];
    drawnPointsRef.current = updated;
    undonePointsRef.current = [];
    undoneSegmentsRef.current = [];
    setCanRedo(false);
    setDrawnPoints([...updated]);
    if (updated.length >= 2) fetchDrawnSegment(updated[updated.length - 2], newPoint);
  };

  const handleDrawUndo = () => {
    if (!drawnPointsRef.current.length) return;
    fetchIdRef.current += 1;
    undonePointsRef.current = [...undonePointsRef.current, drawnPointsRef.current.at(-1)];
    drawnPointsRef.current = drawnPointsRef.current.slice(0, -1);
    if (drawnSegmentsRef.current.length) {
      undoneSegmentsRef.current = [...undoneSegmentsRef.current, drawnSegmentsRef.current.at(-1)];
      drawnSegmentsRef.current = drawnSegmentsRef.current.slice(0, -1);
    }
    setDrawnPoints([...drawnPointsRef.current]);
    setDrawnSegments([...drawnSegmentsRef.current]);
    setDrawingLoading(false);
    setCanRedo(true);
  };

  const handleDrawRedo = () => {
    if (!undonePointsRef.current.length) return;
    const restoredPoint = undonePointsRef.current.at(-1);
    undonePointsRef.current = undonePointsRef.current.slice(0, -1);
    drawnPointsRef.current = [...drawnPointsRef.current, restoredPoint];
    if (undoneSegmentsRef.current.length) {
      drawnSegmentsRef.current = [...drawnSegmentsRef.current, undoneSegmentsRef.current.at(-1)];
      undoneSegmentsRef.current = undoneSegmentsRef.current.slice(0, -1);
    }
    setDrawnPoints([...drawnPointsRef.current]);
    setDrawnSegments([...drawnSegmentsRef.current]);
    setCanRedo(undonePointsRef.current.length > 0);
  };

  useEffect(() => {
    if (routeKind !== "berry" || drawingMode) return;
    setExpeditionPlan(getCachedPlan(lang) || { executive_briefing: t("berryLocalBriefing") });
    if (!ORCHESTRATOR_URL) return;
    const requestId = ++berryFetchIdRef.current;
    fetch(`${ORCHESTRATOR_URL}/api/v1/expedition/plan/berry-mappemonde`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language: lang,
        waypoints: ITINERARY_POINTS.map((p) => ({
          name: p.name, lat: p.lat, lon: p.lon, type: p.flag ? "escale_obligatoire" : "point_intermediaire",
        })),
      }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (routeKindRef.current !== "berry" || berryFetchIdRef.current !== requestId) return;
        if (data?.expedition_plan) {
          setExpeditionPlan(data.expedition_plan);
          setCachedPlan(lang, data.expedition_plan);
        }
      })
      .catch(() => {});
  }, [lang, routeKind, drawingMode, t]);

  useEffect(() => {
    if (routeKind !== "custom" || drawingMode || !customRoute) return;
    fetchCustomPlan(customRoute);
  }, [lang]);

  useEffect(() => { setPoints(ITINERARY_POINTS); }, []);

  useEffect(() => {
    if (!points.length) return undefined;
    const legs = buildBerryLegs(points);
    let cancelled = false;
    (async () => {
      setLoading(true);
      setOfficialFallback(false);
      try {
        const official = await loadOfficialBerryRoute();
        if (cancelled) return;
        setSegments(official.segments);
        setOfficialFallback(false);
        setLoading(false);
        setSegProgress({ done: official.segments.length, total: official.segments.length });
        return;
      } catch { /* searoute si le geojson officiel manque */ }
      setSegProgress({ done: 0, total: legs.length });
      const accumulated = [];
      const fetchLeg = async (leg) => {
        if (isNonMaritimeLeg(leg.from.name, leg.to.name)) {
          return { ...leg, coords: [[leg.from.lon, leg.from.lat], [leg.to.lon, leg.to.lat]], nonMaritime: true };
        }
        try {
          const params = new URLSearchParams({
            start_lat: leg.from.lat, start_lon: leg.from.lon, end_lat: leg.to.lat, end_lon: leg.to.lon, check_wind: false,
          });
          const res = await fetch(`${API_URL}/route?${params}`);
          if (!res.ok) return { ...leg, coords: [], error: `HTTP ${res.status}` };
          const data = await res.json();
          const coords = orientCoords(coordsFromRoutePayload(data), leg.from, leg.to);
          if (!coords.length) return { ...leg, coords: [], error: "empty route" };
          return { ...leg, coords, nonMaritime: false };
        } catch (e) {
          return { ...leg, coords: [], error: e.message };
        }
      };
      for (let i = 0; i < legs.length && !cancelled; i += SEGMENT_BATCH_SIZE) {
        const batch = await Promise.all(legs.slice(i, i + SEGMENT_BATCH_SIZE).map(fetchLeg));
        accumulated.push(...batch);
        if (!cancelled) {
          setSegments(accumulated.filter((r) => r.coords?.length));
          setSegProgress({ done: Math.min(i + SEGMENT_BATCH_SIZE, legs.length), total: legs.length });
          if (i === 0) setLoading(false);
        }
      }
      if (!cancelled) {
        setOfficialFallback(accumulated.every((r) => r.nonMaritime || !r.coords?.length || r.error));
        setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [points]);

  const fetchSatellite = async (lat, lon, extra = {}) => {
    setSatelliteLoading(true);
    setSatelliteTab("wind");
    setSelectedSatellite({ lat, lon, ...extra });
    try {
      const [wind, wave, current] = await Promise.all([
        fetch(`${API_URL}/wind`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ latitude: lat, longitude: lon }) }).then((r) => r.json()),
        fetch(`${API_URL}/wave`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ latitude: lat, longitude: lon }) }).then((r) => r.json()),
        fetch(`${API_URL}/current`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ latitude: lat, longitude: lon }) }).then((r) => r.json()),
      ]);
      setSelectedSatellite((prev) => ({ ...prev, wind, wave, current }));
    } catch {
      setSelectedSatellite((prev) => ({ ...prev, error: true }));
    } finally {
      setSatelliteLoading(false);
    }
  };

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return undefined;
    const onClick = (e) => {
      const { lat, lng: lon } = e.latlng;
      if (drawingMode) { handleDrawingClick(lat, lon); return; }
      const active = customRoute ? featuresToSegments(customRoute) : segments;
      const near = active.some((s) => s.coords?.length > 1 && pointToSegmentPx(map, lat, lon, s.coords) < 16);
      if (near) fetchSatellite(lat, lon);
    };
    const onCtx = (e) => {
      L.DomEvent.preventDefault(e);
      const text = `${e.latlng.lat.toFixed(6)}, ${e.latlng.lng.toFixed(6)}`;
      navigator.clipboard.writeText(text).then(() => {
        setClipboardToast(text);
        setTimeout(() => setClipboardToast(null), 2000);
      });
    };
    map.on("click", onClick);
    map.on("contextmenu", onCtx);
    map.getContainer().style.cursor = drawingMode ? "crosshair" : "";
    return () => {
      map.off("click", onClick);
      map.off("contextmenu", onCtx);
    };
  }, [mapRef, mapReady, drawingMode, segments, customRoute]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return undefined;
    const group = L.layerGroup().addTo(map);
    const src = drawingMode ? drawnPoints.map((p, i) => ({ ...p, name: p.name || `${i + 1}`, flag: "" })) : (customRoute ? [] : points);
    src.forEach((p, i) => {
      if (!p.flag && !drawingMode) return;
      const off = markerOffsets[i] || [0, 0];
      const html = p.flag
        ? `<img src="${typeof p.flag === "string" ? p.flag : p.flag}" alt="" style="height:22px;transform:translate(${off[0]}px,${off[1]}px)" />`
        : `<div style="width:10px;height:10px;border-radius:50%;background:${i === 0 ? "#22c55e" : "#e2e8f0"};border:2px solid #0f172a"></div>`;
      const m = L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: "flag-divicon", html, iconSize: [24, 24], iconAnchor: [12, 12] }),
        interactive: true,
      }).addTo(group);
      m.on("mouseover", () => setHoveredPoint(p));
      m.on("mouseout", () => setHoveredPoint(null));
      if (drawingMode) {
        m.on("click", (ev) => {
          L.DomEvent.stopPropagation(ev);
          setPointInfoName(p.name || "");
          setSelectedSatellite({ lat: p.lat, lon: p.lon, drawPointIndex: i });
        });
      }
    });
    return () => group.remove();
  }, [mapRef, mapReady, points, markerOffsets, drawingMode, drawnPoints, customRoute]);

  const handleSaveDrawPointMeta = () => {
    if (selectedSatellite?.drawPointIndex != null) {
      const idx = selectedSatellite.drawPointIndex;
      const updated = [...drawnPointsRef.current];
      updated[idx] = { ...updated[idx], name: pointInfoName.trim() || undefined, flags: pointInfoFlags.filter(Boolean) };
      drawnPointsRef.current = updated;
      setDrawnPoints([...updated]);
    }
    setSelectedSatellite(null);
  };

  const drawingMessage = drawnPoints.length === 0 ? t("drawStart") : drawnPoints.length === 1 ? t("drawFirstStop") : t("drawNextStop");
  const statsSegs = customRoute ? featuresToSegments(customRoute) : segments;
  const stats = summarizeRoute(statsSegs);

  const enablePendingRestricted = (kind) => {
    if (kind === "balisage") maritimeLayers.setShowBalisage(true);
    if (kind === "bathymetry") maritimeLayers.setShowBathymetry(true);
    if (kind === "fonds") maritimeLayers.setShowFonds(true);
    if (kind === "cables") maritimeLayers.setShowCables(true);
  };

  return (
    <div style={{ height: "100vh", width: "100vw", position: "relative" }} className={isLightMode ? "light-mode" : ""}>
      <div ref={containerRef} id="simulator-map" style={{ height: "100%", width: "100%" }} />

      <NotForNavModal
        open={notForNavOpen}
        onCancel={() => { pendingLayerRef.current = null; setNotForNavOpen(false); }}
        onAccept={() => {
          writeNotForNavAccepted();
          gateRef.current.allowed = true;
          setNotForNavOk(true);
          setNotForNavOpen(false);
          enablePendingRestricted(pendingLayerRef.current);
          pendingLayerRef.current = null;
        }}
      />
      <Sidebar
        plan={expeditionPlan}
        open={sidebarOpen}
        onToggle={() => setSidebarOpen((o) => !o)}
        onCustomRoute={handleCustomRoute}
        onRouteSwitchToBerry={handleRouteSwitchToBerry}
        isDrawing={drawingMode}
        onDrawStart={handleDrawStart}
        onDrawContinue={handleDrawContinue}
        onDrawFinish={handleDrawFinish}
        onCustomDelete={handleCustomDelete}
        canContinueDraw={drawnPoints.length > 0}
        canFinishDraw={drawnPoints.length >= 2 && !drawingLoading}
        isCockpit={false}
        polarData={polarData}
        maritimeLayers={maritimeLayers}
        briefingLoading={iciPack.loading || briefingLoading}
        officialFallback={officialFallback}
        iciBriefing={iciPack.briefing}
        view={view}
        onView={selectView}
        onNext={handleSimNext}
        canNext={playback.nm < ((escaleMarks.at(-1)?.filmNm ?? escaleMarks.at(-1)?.nm) ?? 0) - 1}
        onPrev={handleSimPrev}
        canPrev={playback.nm > ((escaleMarks[0]?.filmNm ?? escaleMarks[0]?.nm) ?? 0) + 1}
        legContext={hudLeg}
        escaleMarks={legendMarks}
        filmNm={playback.nm}
        departureT0={voyage.t0}
        departureStartAt={voyage.startAt}
        onDepartureT0={voyage.setT0}
        onDepartureStartAt={voyage.setStartAt}
        clockSample={clockSample}
        civilDate={civilDate}
        kindLabel={climatologyLabel}
        atQuay={atQuay}
        quayDays={quayDays}
        previewing={previewing}
        forecastStatus={isSuivre && official.gribStatus === "ready" ? "ready" : null}
        forecastModel={isSuivre ? official.gribModel : null}
        onRecompute={() => vessel.recompute(clockSample?.iso)}
        canRecompute={canRecompute}
        recomputeBusy={vessel.busy}
        onGoLive={goLive}
        onSeekEscale={(nm) => {
          lastArrivalKeyRef.current = "";
          setArrivalBanner(null);
          playback.pause();
          playback.seek(nm, { jump: true });
        }}
      />

      <ToolsSidebar
        segments={statsSegs}
        points={customRoute
          ? (customRoute.features || []).filter((f) => f.geometry?.type === "Point").map((f) => ({
            name: f.properties?.name || "", lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], flag: "",
          }))
          : points}
        open={toolsOpen}
        onToggle={() => setToolsOpen((o) => !o)}
        isLightMode={isLightMode}
        onLightModeChange={setIsLightMode}
        polarData={polarData}
        onPolarDataLoaded={setPolarData}
        routeDistanceNm={stats.nm}
        routeSegmentCount={stats.segments}
      />

      {!sceneReady && !drawingMode && (
        <div data-testid="scene-load-mask" className="absolute inset-0 bg-slate-900/80 backdrop-blur-sm flex flex-col items-center justify-center z-[1500] pointer-events-none">
          <div className="w-10 h-10 border-4 border-blue-400/30 border-t-blue-400 rounded-full animate-spin" />
          <div className="mt-4 text-white/90 text-sm font-medium">{t("calculatingRoutes")}</div>
        </div>
      )}

      {!sceneReady && !drawingMode && segProgress.done < segProgress.total && (
        <div className="absolute bottom-20 right-5 z-20 flex items-center gap-2 bg-slate-900/90 text-white text-xs font-medium px-3 py-2 rounded-full shadow-lg pointer-events-none">
          <div className="w-3.5 h-3.5 border-2 border-blue-400/40 border-t-blue-400 rounded-full animate-spin" />
          <span>{t("routesProgress", { done: segProgress.done, total: segProgress.total })}</span>
        </div>
      )}

      {drawingMode && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-[2100] pointer-events-none">
          <div className="flex flex-col items-center gap-1">
            <div className="flex items-center gap-2 bg-slate-900/95 border border-green-500/50 text-white text-sm font-semibold px-4 py-2.5 rounded-full shadow-2xl">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span>{drawingMessage}</span>
              {drawingLoading && <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />}
              <div className="flex gap-1 ml-1 pointer-events-auto">
                <button onClick={handleDrawUndo} disabled={!drawnPoints.length} className="w-7 h-7 flex items-center justify-center rounded-full bg-white/10 disabled:opacity-30" title={t("undoLastPoint")}><Undo2 size={13} /></button>
                <button onClick={handleDrawRedo} disabled={!canRedo} className="w-7 h-7 flex items-center justify-center rounded-full bg-white/10 disabled:opacity-30" title={t("redo")}><Redo2 size={13} /></button>
              </div>
            </div>
            {drawnSegments.some((s) => s.failed) && (
              <div className="bg-orange-950/90 border border-orange-400/50 text-orange-100 text-[11px] font-medium px-3 py-1 rounded-full">
                {t("searouteDrawFailed")}
              </div>
            )}
          </div>
        </div>
      )}

      {clipboardToast && (
        <div className="absolute top-5 left-1/2 -translate-x-1/2 z-30 bg-slate-900/95 text-white text-xs px-4 py-2 rounded-full">
          📋 {clipboardToast} {t("copied")}
        </div>
      )}

      {hoveredPoint && (
        <div className="absolute top-20 left-1/2 -translate-x-1/2 z-20 bg-slate-900/90 text-white text-xs px-3 py-1.5 rounded-full pointer-events-none">
          {hoveredPoint.name}
        </div>
      )}

      {maritimeLayers.showClimatology && (
        <div className="absolute left-1/2 -translate-x-1/2 z-20 bg-sky-950/90 border border-sky-400/40 text-sky-100 text-xs px-4 py-2 rounded-full bottom-48">
          {t("climatologyStub")}
        </div>
      )}

      {(arrivalBanner || playback.holdingStation) && (
        <ArrivalCard
          name={(arrivalBanner || playback.holdingStation).name}
          sailNm={(arrivalBanner || playback.holdingStation).nm}
          seaTime={clockSample
            ? formatFilmClockLine({
              sailNm: clockSample.sailNm,
              seaHours: clockSample.seaHours,
              iso: clockSample.iso,
              lang,
            })
            : formatSeaClock((arrivalBanner || playback.holdingStation).nm, expeditionSpeed.knots)}
          nextName={nextStationAfter(
            (arrivalBanner || playback.holdingStation).filmNm
              ?? (arrivalBanner || playback.holdingStation).nm,
            escaleMarks,
          )?.name}
          holding={playback.holding}
          civilDate={civilDate}
          quayDays={quayDays}
        />
      )}

      <SimulationFilmBar
        fromName={hudLeg?.fromStop}
        toName={hudLeg?.toStop}
        finished={Boolean(hudLeg?.finished)}
        nm={isSuivre && live && !previewing ? (live.sailNm ?? cast?.sailNm ?? 0) : (cast?.sailNm ?? 0)}
        totalNm={playback.sailTotalNm || flatRoute.totalNm}
        playhead={isSuivre && live && !previewing ? (Number(live.filmNm) || playback.nm) : playback.nm}
        playheadTotal={playback.totalNm}
        remainingNm={hudLeg?.remainingNm ?? 0}
        etaHours={hudLeg?.etaHours}
        boatKnots={expeditionSpeed.knots}
        phase={cast?.phase}
        vehicle={cast?.vehicle}
        profile={playback.profile}
        onProfile={playback.setProfile}
        playing={playback.playing}
        onTogglePlay={() => {
          if (isSuivre) setUserPreview(true);
          playback.toggle();
        }}
        marks={escaleMarks}
        onSeekNm={(nm) => {
          lastArrivalKeyRef.current = "";
          setArrivalBanner(null);
          if (isSuivre) setUserPreview(true);
          playback.pause();
          playback.seek(nm, { jump: true });
        }}
        onNext={handleSimNext}
        canNext={playback.nm < ((escaleMarks.at(-1)?.filmNm ?? escaleMarks.at(-1)?.nm) ?? 0) - 1}
        cinema={cinemaMode}
        onCinema={toggleCinema}
        hideBar={cinemaMode && hideFilmBar}
        onHideBar={setHideFilmBar}
        liveSpeed={expeditionSpeed.live}
        boatName={polarData?.boat_name}
        windSeries={windProfile.series}
        windLoading={windProfile.loading}
        holding={playback.holding}
        clockLine={clockLine}
        atQuay={atQuay}
        quayDays={quayDays}
        twa={clockSample?.twa}
        liveBadge={isSuivre ? (previewing ? t("previewBadge") : "LIVE") : null}
        windKind={clockSample?.kind === "forecast" ? "forecast" : (isSuivre ? null : (clockSample?.kind || expeditionSpeed.kind))}
        windModel={isSuivre ? official.gribModel : (clockSample?.model || official.gribModel)}
        showSpeeds={isSimulation}
        showWindProfile={false}
        stopAuto={stopAuto}
        onStopAuto={setStopAuto}
        showStopAuto={isSimulation}
        sidebarOpen={sidebarOpen}
        toolsOpen={toolsOpen}
        gribLine={isSuivre && official.gribStatus !== "ready" && official.gribStatus !== "pending" ? t("gribMissing") : ""}
        clock={officialClock}
        clockCurrent={clockSample ? {
          filmNm: isSuivre && live && !previewing ? (Number(live.filmNm) || 0) : playback.nm,
          sailNm: clockSample.sailNm,
          seaHours: clockSample.seaHours,
        } : null}
        disclaimer={t("creditsLine")}
      />

      <RecomputeDialog
        draft={vessel.draft}
        busy={vessel.busy}
        onAccept={async () => { await vessel.accept(); }}
        onReject={() => vessel.reject()}
      />

      <LayerFichePopup popup={layerPopup} onClose={() => setLayerPopup(null)} />

      {selectedSatellite && (
        <div className="absolute left-1/2 -translate-x-1/2 z-[2100] w-[320px] bg-slate-900/96 border border-white/10 rounded-xl p-3 text-white text-xs shadow-2xl bottom-52">
          <button type="button" className="absolute top-2 right-2 text-slate-400" onClick={() => setSelectedSatellite(null)}><X size={14} /></button>
          <div className="font-semibold mb-2">{t("satelliteData")}</div>
          <div className="flex gap-1 mb-2">
            {["wind", "waves", "currents"].map((tab) => (
              <button key={tab} type="button" onClick={() => setSatelliteTab(tab)} className={`px-2 py-1 rounded ${satelliteTab === tab ? "bg-blue-600" : "bg-slate-800"}`}>
                {tab === "wind" ? t("windTab") : tab === "waves" ? t("wavesTab") : t("currentsTab")}
              </button>
            ))}
          </div>
          {satelliteLoading && <p>{t("fetchingSatellite")}</p>}
          {!satelliteLoading && satelliteTab === "wind" && (
            selectedSatellite.wind
              ? (
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <WindDirectionArrow direction={selectedSatellite.wind.wind_direction} />
                    <span>{t("windSpeed")} {selectedSatellite.wind.wind_speed_knots} kt</span>
                  </div>
                  <div>{t("windDirection")} {getCardinalDirection(selectedSatellite.wind.wind_direction)}</div>
                </div>
              )
              : <p>{t("noWindData")}</p>
          )}
          {!satelliteLoading && satelliteTab === "waves" && (
            selectedSatellite.wave
              ? <div>{t("waveHeight")} {selectedSatellite.wave.significant_wave_height_m} m · {t("wavePeriod")} {selectedSatellite.wave.mean_wave_period} s</div>
              : <p>{t("noWaveData")}</p>
          )}
          {!satelliteLoading && satelliteTab === "currents" && (
            selectedSatellite.current
              ? <div>{t("currentSurfaceSpeed")} {selectedSatellite.current.speed_knots} kt</div>
              : <p>{t("noCurrentData")}</p>
          )}
          {selectedSatellite.drawPointIndex != null && (
            <div className="mt-2 border-t border-white/10 pt-2">
              <label className="block text-slate-400 mb-1">{t("waypointName")}</label>
              <input value={pointInfoName} onChange={(e) => setPointInfoName(e.target.value)} className="w-full bg-slate-800 rounded px-2 py-1" placeholder={t("waypointNamePlaceholder")} />
              <button type="button" onClick={handleSaveDrawPointMeta} className="mt-2 w-full bg-blue-600 rounded py-1">{t("saveClose")}</button>
            </div>
          )}
        </div>
      )}

    </div>
  );
}
