import { ChevronRight, Clapperboard, Pause, Play } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { filmBarInsets } from "../utils/filmBarLayout.js";

const PROFILES = [
  { id: "real", labelKey: "speedReal" },
  { id: "read", labelKey: "speedRead" },
  { id: "normal", labelKey: "speedNormal" },
  { id: "fast", labelKey: "speedFast" },
];

export function SimulationFilmBar({
  fromName,
  toName,
  finished,
  nm,
  totalNm,
  playhead,
  playheadTotal,
  remainingNm,
  etaHours,
  boatKnots,
  profile,
  onProfile,
  playing,
  onTogglePlay,
  marks,
  onSeekNm,
  onNext,
  canNext,
  cinema,
  onCinema,
  hideBar = false,
  onHideBar,
  liveSpeed,
  windKind,
  boatName,
  phase,
  vehicle,
  windSeries,
  windLoading,
  holding,
  clockLine = "",
  atQuay = false,
  quayDays = 0,
  twa = null,
  liveBadge = null,
  windModel = null,
  showSpeeds = false,
  showWindProfile = false,
  stopAuto = false,
  onStopAuto,
  showStopAuto = false,
  sidebarOpen = true,
  toolsOpen = true,
  gribLine = "",
  clock = null,
  clockCurrent = null,
  disclaimer = "",
}) {
  const { t } = useLang();
  const insets = filmBarInsets({ sidebarOpen, toolsOpen });
  const barTotal = playheadTotal ?? totalNm;
  const barNm = playhead ?? nm;
  const pct = barTotal > 0 ? Math.min(100, (barNm / barTotal) * 100) : 0;
  const phaseLabel = phase === "air-out" || phase === "air"
    ? t("filmPhaseAir")
    : phase === "air-return"
      ? t("filmPhaseAirReturn")
      : phase === "side-sail"
        ? t("filmPhaseSide")
        : "";
  const onBarClick = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const t0 = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    onSeekNm(t0 * barTotal);
  };

  if (hideBar) {
    return (
      <div
        className="absolute bottom-5 z-[2020] pointer-events-auto"
        style={{ left: insets.left, right: insets.right }}
      >
        <button
          type="button"
          onClick={() => onHideBar?.(false)}
          className="mx-auto block px-2 py-1 rounded-md text-[10px] font-semibold bg-slate-950/80 border border-white/15 text-white/80"
        >
          {t("showFilmBar")}
        </button>
      </div>
    );
  }

  return (
    <div
      data-testid="film-bar"
      className="absolute bottom-5 z-[2020] pointer-events-auto"
      style={{ left: insets.left, right: insets.right }}
    >
      <div className="rounded-xl border border-white/15 bg-slate-950/92 shadow-2xl px-2.5 pt-1.5 pb-1.5 text-white backdrop-blur-sm">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0 text-[12px] font-semibold leading-tight truncate">
            {finished
              ? t("filmArrived", { name: fromName || "—" })
              : (
                <>
                  <span className="text-blue-200">{fromName || "—"}</span>
                  <span className="text-white/35 mx-1">→</span>
                  <span className="text-cyan-200">{toName || "—"}</span>
                </>
              )}
            {phaseLabel ? <span className="text-[10px] font-normal text-cyan-300/80 ml-2">{phaseLabel}</span> : null}
          </div>
          <div className="flex flex-shrink-0 items-center gap-1">
            {disclaimer ? (
              <span data-testid="nav-disclaimer" className="text-[9px] text-amber-100/80 leading-tight max-w-[9rem] text-right">
                {disclaimer}
              </span>
            ) : null}
            {cinema && onHideBar ? (
              <button
                type="button"
                onClick={() => onHideBar(true)}
                className="px-2 py-0.5 rounded-md text-[10px] font-semibold border bg-white/5 border-white/10 hover:bg-white/10"
              >
                {t("hideFilmBar")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onCinema}
              className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold border ${
                cinema ? "bg-cyan-700/70 border-cyan-400/50" : "bg-white/5 border-white/10 hover:bg-white/10"
              }`}
              title={t("cinemaTooltip")}
            >
              <Clapperboard size={11} />
              {t("cinema")}
            </button>
          </div>
        </div>

        <div data-testid="film-clock-line" className="text-[11px] text-white/75 tabular-nums leading-tight mt-0.5 truncate">
          {clockLine || `${Math.round(nm).toLocaleString()} nm`}
          {remainingNm > 0.5 && !finished && vehicle !== "plane"
            ? ` · ${t("nmRemaining")} ${Math.round(remainingNm).toLocaleString()} nm`
            : ""}
          {etaHours != null && etaHours > 0 && !finished && vehicle !== "plane" ? ` · ${t("eta")} ${formatEta(etaHours)}` : ""}
          {vehicle === "plane" ? ` · ${t("filmAirVehicle")}` : ` · ${Number(boatKnots || 0).toFixed(1)} kt`}
          {twa != null && vehicle !== "plane" ? ` · ${t("voyageTwa", { deg: Math.round(twa) })}` : ""}
          {boatName && vehicle !== "plane" ? ` · ${boatName}` : ""}
          {liveBadge ? ` · ${liveBadge}` : ""}
          {atQuay && quayDays > 0 ? ` · ${t("voyageAtQuay", { days: quayDays })}` : (holding ? ` · ${t("filmArrivalHold")}` : "")}
          {windKind === "forecast" && windModel ? ` · ${windModel}` : ""}
        </div>
        {gribLine ? (
          <div data-testid="grib-warning" className="text-[10px] text-amber-200/90 leading-tight">
            {gribLine}
          </div>
        ) : null}

        <button
          type="button"
          onClick={onBarClick}
          className="relative w-full h-2 rounded-full bg-white/10 block mt-1"
          title={t("filmScrub")}
        >
          <span className="absolute inset-y-0 left-0 rounded-full bg-cyan-400/80" style={{ width: `${pct}%` }} />
          {(marks || []).map((m) => (
            <span
              key={`${m.name}-${m.nm}`}
              className="absolute top-1/2 -translate-y-1/2 w-1.5 h-1.5 rounded-full bg-white"
              style={{ left: `${barTotal > 0 ? ((m.filmNm ?? m.nm) / barTotal) * 100 : 0}%` }}
              title={m.name}
            />
          ))}
        </button>

        <div className="flex items-center gap-1.5 mt-1">
          <button
            type="button"
            onClick={onTogglePlay}
            className="w-9 h-7 rounded-md bg-cyan-600 hover:bg-cyan-500 flex items-center justify-center"
            title={playing ? t("pause") : t("play")}
          >
            {playing ? <Pause size={14} /> : <Play size={14} className="ml-0.5" />}
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={!canNext}
            className="h-7 px-2 rounded-md bg-white/10 disabled:opacity-30 flex items-center gap-1 text-[10px] font-semibold"
            title={t("goToNextStop")}
          >
            <ChevronRight size={14} />
            {t("goToNextStop")}
          </button>
          {showStopAuto ? (
            <button
              type="button"
              data-testid="stop-auto"
              role="switch"
              aria-checked={stopAuto}
              onClick={() => onStopAuto?.(!stopAuto)}
              className={`h-7 px-2 rounded-md text-[10px] font-semibold border ${
                stopAuto
                  ? "bg-amber-600/80 border-amber-300/50"
                  : "bg-white/5 border-white/10 text-white/70"
              }`}
              title={stopAuto ? t("stopAutoOn") : t("stopAutoOff")}
            >
              {t("stopAuto")}
            </button>
          ) : null}

          {showSpeeds ? (
            <div className="flex flex-wrap gap-1 ml-1">
              {PROFILES.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => onProfile(p.id)}
                  className={`px-2 py-0.5 rounded-md text-[10px] font-semibold border ${
                    profile === p.id
                      ? "bg-white text-slate-900 border-white"
                      : "bg-white/5 border-white/10 text-white/70 hover:text-white"
                  }`}
                  title={t(`${p.labelKey}Title`)}
                >
                  {t(p.labelKey)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function formatEta(hours) {
  if (hours == null || Number.isNaN(hours)) return "—";
  if (hours < 1 / 60) return "0 min";
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (hours >= 48) return `${Math.round(hours / 24)} j`;
  if (m === 0) return `${h} h`;
  return `${h} h ${String(m).padStart(2, "0")}`;
}
