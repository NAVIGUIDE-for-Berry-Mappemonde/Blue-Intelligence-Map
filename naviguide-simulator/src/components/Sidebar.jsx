import { useState } from "react";
import { CheckCircle, ChevronLeft, ChevronRight, Pencil, Shield, Trash2 } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { SimulationPanel } from "./SimulationPanel";
import { EscaleLegend } from "./EscaleLegend.jsx";
import { DepartureField } from "./DepartureField.jsx";
import { ViewModeSwitch } from "./ViewModeSwitch.jsx";
import { ALL_LAYER_CONFIG } from "../constants/layers.js";
import { VIEW_SIMULATION, VIEW_SUIVRE } from "../constants/viewMode.js";

const NAVIGUIDE_LOGO = "/logo-naviguide.png";
const BERRY_LOGO = "/logo-berry-mappemonde.svg";

function BerryCard({
  onCustomRoute, onRouteSwitchToBerry, isDrawing,
  onDrawStart, onDrawContinue, onDrawFinish, onCustomDelete, canContinueDraw,
  canFinishDraw = true,
}) {
  const { t } = useLang();
  const [cardMode, setCardMode] = useState("berry-active");
  const [drawnRoute, setDrawnRoute] = useState(null);
  const [drawnName, setDrawnName] = useState(null);
  const hasCustom = Boolean(drawnRoute);
  const customOn = cardMode === "file-active";

  const activateBerry = () => {
    setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
    onRouteSwitchToBerry();
  };

  const activateCustom = () => {
    if (!drawnRoute) return;
    setCardMode("file-active");
    onCustomRoute(drawnRoute);
  };

  const handleFinishDrawing = () => {
    const geojson = onDrawFinish();
    if (geojson?.features?.length > 0) {
      setDrawnRoute(geojson);
      setDrawnName(t("customRoute"));
      setCardMode("file-active");
      onCustomRoute(geojson);
    } else {
      setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
    }
  };

  const handleDelete = (e) => {
    e.stopPropagation();
    setDrawnRoute(null);
    setDrawnName(null);
    setCardMode("berry-active");
    onCustomDelete?.();
    onRouteSwitchToBerry();
  };

  const pillOn = "flex-1 min-w-0 px-2 py-1.5 rounded-lg text-[10px] font-semibold leading-tight border border-blue-400/60 bg-blue-600/30 text-blue-100";
  const pillOff = "flex-1 min-w-0 px-2 py-1.5 rounded-lg text-[10px] font-semibold leading-tight border border-slate-600/50 bg-slate-800/50 text-slate-400 hover:text-white hover:border-slate-500";

  const switcher = hasCustom ? (
    <div className="flex gap-1 mb-1.5">
      <button type="button" onClick={activateBerry} className={customOn ? pillOff : pillOn} title={t("backToBerry")}>
        {t("berryMappemonde")} {/* pragma: allowlist secret */}
      </button>
      <button type="button" onClick={activateCustom} className={customOn ? pillOn : pillOff} title={t("showRoute", { name: drawnName })}>
        {drawnName || t("customRoute")}
      </button>
    </div>
  ) : null;

  if (cardMode === "draw-mode" || isDrawing) {
    return (
      <div className="rounded-lg px-2 py-1.5 border border-slate-700/50 bg-slate-800/60">
        {switcher}
        {isDrawing ? (
          <button
            onClick={handleFinishDrawing}
            disabled={!canFinishDraw}
            className="w-full flex items-center justify-center gap-1.5 bg-green-600/30 hover:bg-green-600/50
              border border-green-500/50 rounded-lg px-2 py-1.5 text-[10px] text-green-300 font-semibold
              disabled:opacity-40 disabled:pointer-events-none"
          >
            <CheckCircle size={11} /> {t("finish")}
          </button>
        ) : (
          <button
            onClick={() => { setCardMode("draw-mode"); onDrawStart(); }}
            className="w-full flex items-center justify-center gap-1.5 bg-violet-600/20 hover:bg-violet-600/40
              border border-violet-500/40 rounded-lg px-2 py-1.5 text-[10px] text-violet-300 font-medium"
          >
            <Pencil size={11} /> {t("drawOwnRoute")}
          </button>
        )}
      </div>
    );
  }

  if (cardMode === "file-active") {
    return (
      <div className="rounded-lg px-2 py-1.5 border border-blue-500/70 bg-blue-950/30">
        {switcher}
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => { setCardMode("draw-mode"); (canContinueDraw ? onDrawContinue : onDrawStart)?.(); }}
            className="flex-1 flex items-center justify-center gap-1 px-1.5 py-1 rounded-lg text-[10px]
              font-medium border border-violet-500/40 text-violet-300 hover:bg-violet-600/20"
          >
            <Pencil size={10} /> {canContinueDraw ? t("continueDrawing") : t("drawOwnRoute")}
          </button>
          <button
            type="button"
            onClick={handleDelete}
            title={t("deleteCustomRoute")}
            className="flex items-center justify-center px-2 py-1 rounded-lg text-[10px]
              border border-red-500/40 text-red-300 hover:bg-red-600/20"
          >
            <Trash2 size={10} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg px-2 py-1.5 border border-blue-500/70 bg-blue-950/30">
      {switcher}
      <button
        onClick={() => { setCardMode("draw-mode"); onDrawStart(); }}
        title={t("drawOwnRoute")}
        className="w-full flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-blue-900/30 cursor-pointer"
      >
        <img src={BERRY_LOGO} alt="Berry-Mappemonde" className="h-7 w-auto object-contain rounded flex-shrink-0" style={{ maxWidth: 48 }} /> {/* pragma: allowlist secret */}
        <div className="text-left">
          <div className="text-white font-bold text-[11px] leading-tight tracking-wide">{t("berryMappemonde")}</div> {/* pragma: allowlist secret */}
          <div className="text-[10px] text-violet-300">{t("drawOwnRoute")}</div>
        </div>
      </button>
    </div>
  );
}

export function Sidebar({
  plan, open, onToggle, onCustomRoute, onRouteSwitchToBerry, isDrawing,
  onDrawStart, onDrawContinue, onDrawFinish, onCustomDelete, canContinueDraw,
  canFinishDraw,
  isCockpit, polarData, maritimeLayers, view = VIEW_SUIVRE, onView,
  legContext, onNext, canNext, onPrev, canPrev, briefingLoading, officialFallback,
  iciBriefing = null,
  escaleMarks = [], filmNm = 0, onSeekEscale,
  departureT0, departureStartAt, onDepartureT0, onDepartureStartAt,
  clockSample = null, civilDate = "", kindLabel = "", atQuay = false, quayDays = 0,
  previewing = false, forecastStatus = null, forecastModel = null,
  onRecompute, canRecompute = false, recomputeBusy = false, onGoLive,
}) {
  const { t } = useLang();
  const isSimulation = view === VIEW_SIMULATION;
  const isSuivre = view === VIEW_SUIVRE;
  const expeditionBriefing = plan?.executive_briefing || "";
  const briefing = iciBriefing || expeditionBriefing;

  return (
    <>
      <button
        onClick={onToggle}
        className={`naviguide-sidebar-toggle absolute top-4 z-30 bg-slate-900/95 text-white
          rounded-full flex items-center justify-center shadow-lg
          hover:bg-slate-800 transition-all duration-300
          w-9 h-9 border border-slate-700
          ${open ? "left-[322px]" : "left-4"}`}
        title={open ? t("hideSidebar") : t("showExpeditionPanel")}
      >
        {open ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
      </button>

      <div
        className={`naviguide-sidebar-panel absolute top-0 left-0 h-full z-20 flex flex-col bg-slate-900/97
          shadow-2xl transition-transform duration-300 border-r border-slate-700/60
          ${open ? "translate-x-0" : "-translate-x-full"}`}
        style={{ width: 320 }}
      >
        <div className="px-3 pt-2 pb-2 border-b border-slate-700/60 flex-shrink-0">
          <div className="flex items-center gap-2 mb-1.5">
            <img src={NAVIGUIDE_LOGO} alt={t("brandTitle")} className="h-12 w-12 object-contain drop-shadow" />
            <span className="text-white font-bold text-[11px] leading-tight tracking-wide">{t("brandTitle")}</span>
          </div>

          <BerryCard
            onCustomRoute={onCustomRoute}
            onRouteSwitchToBerry={onRouteSwitchToBerry}
            isDrawing={isDrawing}
            onDrawStart={onDrawStart}
            onDrawContinue={onDrawContinue}
            onDrawFinish={onDrawFinish}
            onCustomDelete={onCustomDelete}
            canContinueDraw={canContinueDraw}
            canFinishDraw={canFinishDraw}
          />

          {maritimeLayers && (
            <div className="flex flex-wrap gap-1 mt-2">
              {ALL_LAYER_CONFIG.map(({ key, labelKey, titleKey, color, showKey, toggleKey, loadingKey, errorKey }) => {
                const active = maritimeLayers[showKey];
                const loading = maritimeLayers[loadingKey];
                const error = maritimeLayers[errorKey];
                return (
                  <button
                    key={key}
                    onClick={() => maritimeLayers[toggleKey]((v) => !v)}
                    title={error ? `${t(titleKey)} : ${error}` : t(titleKey)}
                    className={[
                      "flex items-center justify-center gap-1 px-1.5 py-0.5 rounded-full",
                      "text-[9px] font-semibold transition-all duration-150 select-none",
                      active
                        ? "bg-slate-700/80 text-white border border-white/10"
                        : "bg-slate-800/30 text-white/40 border border-white/5 hover:text-white/70",
                    ].join(" ")}
                  >
                    {loading
                      ? <div className="w-1.5 h-1.5 rounded-full border border-white/30 border-t-white animate-spin flex-shrink-0" />
                      : <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: active ? color : "transparent", border: `1.5px solid ${error ? "#ef4444" : color}` }} />}
                    {t(labelKey)}
                  </button>
                );
              })}
            </div>
          )}

          {!isDrawing && onView ? (
            <ViewModeSwitch view={view} onView={onView} />
          ) : null}
        </div>

        <div className="flex-1 overflow-y-auto sidebar-scroll px-4 py-2 space-y-2">
          {isSuivre && (
            <p className="text-[10px] text-sky-100/80 border border-white/10 rounded-lg px-2 py-1.5">
              {t("officialDepartureLocked")}
            </p>
          )}
          {isSimulation && (
            <DepartureField
              t0={departureT0}
              startAt={departureStartAt}
              onT0={onDepartureT0}
              onStartAt={onDepartureStartAt}
            />
          )}
          <SimulationPanel
            legContext={legContext}
            onPrev={onPrev}
            canPrev={canPrev}
            onNext={onNext}
            canNext={canNext}
            clockSample={clockSample}
            civilDate={civilDate}
            kindLabel={kindLabel}
            atQuay={atQuay}
            quayDays={quayDays}
            liveFollow={isSuivre}
            previewing={previewing}
            forecastStatus={isSuivre ? forecastStatus : null}
            forecastModel={forecastModel}
            onRecompute={onRecompute}
            canRecompute={canRecompute}
            showRecompute={isSimulation}
            recomputeBusy={recomputeBusy}
            onGoLive={onGoLive}
          />
          <EscaleLegend marks={escaleMarks} filmNm={filmNm} onSeek={onSeekEscale} />

          {officialFallback && (
            <p className="text-[10px] text-amber-300/90 border border-amber-500/30 rounded-lg px-2 py-1.5">
              {t("searouteUnavailable")}
            </p>
          )}

          {!isCockpit && !plan && !briefingLoading && !isDrawing && (
            <div className="rounded-xl border border-blue-700/30 bg-blue-950/20 p-3">
              <div className="text-xs font-semibold text-blue-300 mb-1.5">{t("gettingStarted")}</div>
              <p className="text-xs text-slate-400 leading-relaxed">{t("gettingStartedText")}</p>
            </div>
          )}

          {isDrawing && (
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Shield size={12} className="text-blue-400" />
                {t("briefing")}
              </div>
              <div className="bg-slate-800/50 rounded-xl p-3 border border-slate-700/50">
                <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-line">{t("briefingDrawHint")}</p>
              </div>
            </div>
          )}

          {!isDrawing && (isCockpit || briefing || briefingLoading) && (
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Shield size={12} className="text-blue-400" />
                {t("briefing")}
              </div>
              <div className="bg-slate-800/50 rounded-xl p-3 border border-slate-700/50">
                <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-line">
                  {briefingLoading
                    ? t("iciBriefingLoading")
                    : (briefing || t("iciBriefingFallback"))}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
