/**
 * SimulationPanel — Shows catamaran progress metrics
 *
 * Purely geometric calculation from useLegContext.
 * No API call — data available instantly on drag.
 *
 * Props:
 *   legContext   — LegContext object from the useLegContext hook
 *   onAdvance    — callback to advance to the midpoint of the next segment
 *   canAdvance   — boolean, disables the button at the end of the route
 */

import { Navigation, Clock, Compass, Map as MapIcon, ChevronLeft, ChevronRight } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";

// ── Formatting ────────────────────────────────────────────────────────────────

function formatEta(hours) {
  if (hours == null || Number.isNaN(hours)) return "—";
  if (hours < 1 / 60) return "0 min";
  if (hours < 1) return `${Math.round(hours * 60)} min`;
  if (hours >= 48) return `${Math.round(hours / 24)} j`;
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (m === 0) return `${h} h`;
  return `${h} h ${String(m).padStart(2, "0")}`;
}

function formatNm(nm) {
  if (nm == null) return "—";
  return `${nm.toLocaleString()} nm`;
}

function formatBearing(deg) {
  if (deg == null) return "—";
  const dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSO","SO","OSO","O","ONO","NO","NNO"];
  const idx = Math.round(deg / 22.5) % 16;
  return `${Math.round(deg)}° ${dirs[idx]}`;
}

// ── Previous / Next buttons ──────────────────────────────────────────────

function PrevNextButtons({ onPrev, canPrev, onNext, canNext }) {
  const { t } = useLang();
  const btnBase = "flex-1 flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg text-[10px] font-semibold transition-all duration-150 select-none border";
  const btnActive = "text-white cursor-pointer";
  const btnDisabled = "bg-slate-700/30 text-white/25 border-white/5 cursor-not-allowed";
  return (
    <div className="px-1.5 pb-1.5 pt-0.5 flex gap-1">
      <button
        onClick={onPrev}
        disabled={!canPrev}
        className={[btnBase, canPrev ? `${btnActive} bg-slate-700/60 border-slate-500/50 hover:bg-slate-600/70` : btnDisabled].join(" ")}
        title={t("previousEscale")}
      >
        <ChevronLeft size={10} />
        <span>{t("previous")}</span>
      </button>
      <button
        onClick={onNext}
        disabled={!canNext}
        className={[btnBase, canNext ? `${btnActive} bg-cyan-700/60 border-cyan-500/50 hover:bg-cyan-600/70` : btnDisabled].join(" ")}
        title={t("nextEscale")}
      >
        <span>{t("next")}</span>
        <ChevronRight size={10} />
      </button>
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────

export function SimulationPanel({
  legContext,
  onPrev,
  canPrev,
  onNext,
  canNext,
  clockSample = null,
  civilDate = "",
  kindLabel = "",
  atQuay = false,
  quayDays = 0,
  liveFollow = false,
  previewing = false,
  forecastStatus = null,
  forecastModel = null,
  onRecompute,
  canRecompute = false,
  showRecompute = false,
  recomputeBusy = false,
  onGoLive,
}) {
  const { t } = useLang();

  if (!legContext) {
    return (
      <div className="bg-slate-800/60 rounded-lg p-2 border border-blue-700/30">
        <div className="text-[10px] text-slate-400 text-center">
          {t("simulationDragPrompt")}
        </div>
        <div className="mt-1">
          <PrevNextButtons onPrev={onPrev} canPrev={canPrev} onNext={onNext} canNext={canNext} />
        </div>
      </div>
    );
  }

  const {
    fromStop, toStop,
    nmCovered, nmRemainingToStop,
    etaHours, bearing, speedKnots,
    finished,
  } = legContext;

  return (
    <div className="bg-slate-800/70 rounded-lg border border-blue-600/30 overflow-hidden">

      <div className="flex items-center justify-between px-2 py-1 bg-blue-900/30 border-b border-blue-700/20">
        <div className="flex items-center gap-1 min-w-0 flex-wrap">
          <Navigation size={10} className="text-blue-400 flex-shrink-0" />
          <span className="text-[10px] font-semibold text-blue-300 leading-tight">
            {finished ? t("filmArrived", { name: fromStop }) : fromStop}
          </span>
          {!finished && (
            <>
              <span className="text-white/30 text-[10px]">→</span>
              <span className="text-[10px] font-semibold text-cyan-300 leading-tight">
                {toStop}
              </span>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-px bg-slate-700/20">

        <div className="bg-slate-800/60 px-2 py-1 flex flex-col">
          <div className="flex items-center gap-1">
            <MapIcon size={9} className="text-cyan-400" />
            <span className="text-[8px] text-slate-400 uppercase tracking-wider">
              {t("nmRemaining")}
            </span>
          </div>
          <span className="text-xs font-bold text-white leading-tight">{formatNm(nmRemainingToStop)}</span>
        </div>

        <div className="bg-slate-800/60 px-2 py-1 flex flex-col">
          <div className="flex items-center gap-1">
            <Clock size={9} className="text-amber-400" />
            <span className="text-[8px] text-slate-400 uppercase tracking-wider">
              {t("eta")}
            </span>
          </div>
          <span className="text-xs font-bold text-white leading-tight">{formatEta(etaHours)}</span>
          <span className="text-[8px] text-slate-500 leading-tight">
            {clockSample?.vehicle === "plane"
              ? t("filmAirVehicle")
              : clockSample?.speedKnots != null
                ? t("voyageLocalKnots", { knots: Number(clockSample.speedKnots).toFixed(1) })
                : speedKnots != null
                  ? t("voyageLocalKnots", { knots: speedKnots })
                  : "—"}
          </span>
        </div>

        <div className="bg-slate-800/60 px-2 py-1 flex flex-col">
          <div className="flex items-center gap-1">
            <Navigation size={9} className="text-green-400" />
            <span className="text-[8px] text-slate-400 uppercase tracking-wider">
              {t("nmCovered")}
            </span>
          </div>
          <span className="text-xs font-bold text-white leading-tight">{formatNm(nmCovered)}</span>
        </div>

        <div className="bg-slate-800/60 px-2 py-1 flex flex-col">
          <div className="flex items-center gap-1">
            <Compass size={9} className="text-purple-400" />
            <span className="text-[8px] text-slate-400 uppercase tracking-wider">
              {t("bearing")}
            </span>
          </div>
          <span className="text-xs font-bold text-white leading-tight">{formatBearing(bearing)}</span>
        </div>

      </div>

      {(civilDate || kindLabel || clockSample?.twa != null || atQuay) && (
        <div className="px-2 py-1 text-[9px] text-sky-100/90 border-t border-white/5 space-y-0 leading-tight">
          {civilDate ? <div>{civilDate}</div> : null}
          <div className="flex flex-wrap gap-x-2 text-white/55">
            {kindLabel ? <span>{kindLabel}</span> : null}
            {clockSample?.twa != null && clockSample?.vehicle !== "plane" ? (
              <span>{t("voyageTwa", { deg: Math.round(clockSample.twa) })}</span>
            ) : null}
          </div>
          {atQuay && quayDays > 0 ? (
            <div className="text-amber-200 font-semibold uppercase tracking-wide">
              {t("voyageAtQuay", { days: quayDays })}
            </div>
          ) : null}
          {clockSample?.kind === "forecast" && (clockSample.model || forecastModel) ? (
            <div className="text-cyan-200/80">
              {clockSample.model || forecastModel}
              {clockSample.leadHours != null ? ` · +${Math.round(clockSample.leadHours)} h` : ""}
            </div>
          ) : null}
        </div>
      )}

      {liveFollow && (
        <div className="px-2 py-1 border-t border-white/5 flex items-center justify-between gap-2">
          <span className={`text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded ${
            previewing ? "bg-slate-600/40 text-slate-300" : "bg-emerald-500/20 text-emerald-300"
          }`}
          >
            {previewing ? t("previewBadge") : "LIVE"}
          </span>
          {clockSample?.status === "waiting" && clockSample.countdownHours != null ? (
            <span className="text-[9px] text-amber-200/90">
              {t("departsIn", { hours: formatEta(clockSample.countdownHours) })}
            </span>
          ) : null}
          {previewing && onGoLive ? (
            <button
              type="button"
              onClick={onGoLive}
              className="text-[9px] font-semibold text-cyan-200 hover:text-cyan-100"
              title="L"
            >
              {t("returnToLive")}
            </button>
          ) : null}
        </div>
      )}

      {forecastStatus === "pending" && (
        <div className="px-2 py-1 text-[9px] text-sky-200/80 bg-sky-950/40">{t("forecastPending")}</div>
      )}
      {forecastStatus === "unavailable" && (
        <div className="px-2 py-1 text-[9px] text-amber-200/80 bg-amber-950/30">{t("forecastUnavailable")}</div>
      )}

      {showRecompute && (
        <div className="px-1.5 pb-1.5">
          <button
            type="button"
            disabled={!canRecompute || recomputeBusy || forecastStatus === "pending"}
            onClick={onRecompute}
            className="w-full rounded-md border border-cyan-500/40 bg-cyan-900/30 py-1 text-[10px] font-semibold text-cyan-100 hover:bg-cyan-800/40 disabled:opacity-40"
          >
            {recomputeBusy ? t("recomputeBusy") : t("recomputeButton")}
          </button>
        </div>
      )}

      {/* Previous / Next buttons */}
      <PrevNextButtons onPrev={onPrev} canPrev={canPrev} onNext={onNext} canNext={canNext} />

    </div>
  );
}
