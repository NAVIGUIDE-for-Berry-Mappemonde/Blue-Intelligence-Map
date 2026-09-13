/**
 * NAVIGUIDE v2 — Expedition Sidebar
 * Shows voyage statistics, LLM executive briefing, and critical alerts.
 * The Berry-Mappemonde card is an interactive route switcher with file import.
 */
import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Shield, Upload, X, Pencil, CheckCircle, Send, Loader2, Compass, Play, Square, Trash2 } from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";
import { SimulationPanel } from "./SimulationPanel";
import { AgentPanel } from "./AgentPanel";
import { ALL_LAYER_CONFIG } from "./MaritimeLayers";

const POLAR_API_URL = import.meta.env.VITE_POLAR_API_URL ?? "http://localhost:8004";

/* ── Polar Chat bubble ───────────────────────────────────────────────────── */
function PolarChatBubble({ role, content }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-1.5`}>
      <div className={`max-w-[88%] px-3 py-2 rounded-xl text-xs leading-relaxed whitespace-pre-wrap
        ${isUser
          ? "bg-blue-600 text-white rounded-br-none"
          : "bg-slate-700/80 text-slate-200 rounded-bl-none border border-slate-600/40"
        }`}>
        {content}
      </div>
    </div>
  );
}

/* ── Polar Chat section (rendered inside Sidebar above briefing) ────────── */
function PolarChatSection({ polarData }) {
  const { t } = useLang();
  const [messages,    setMessages]    = useState([]);
  const [chatInput,   setChatInput]   = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatListRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    const el = chatListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // Auto-resize textarea as content grows/shrinks
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 112) + "px";
  }, [chatInput]);

  const handleSend = async () => {
    const msg = chatInput.trim();
    if (!msg || chatLoading || !polarData?.expedition_id) return;
    const userMsg     = { role: "user", content: msg };
    const nextHistory = [...messages, userMsg];
    setMessages(nextHistory);
    setChatInput("");
    setChatLoading(true);
    try {
      const res  = await fetch(`${POLAR_API_URL}/api/v1/polar/chat`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          expedition_id: polarData.expedition_id,
          message:       msg,
          history:       messages.slice(-6),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
      setMessages([...nextHistory, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setMessages([...nextHistory, { role: "assistant", content: `⚠️ ${err.message}` }]);
    } finally {
      setChatLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <div>
      <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
        <Compass size={12} className="text-blue-400" />
        Chat
      </div>

      {/* Messages */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden">
        <div ref={chatListRef} className="max-h-48 overflow-y-auto sidebar-scroll px-3 py-3 space-y-0.5">
          {messages.length === 0 && !polarData && (
            <p className="text-xs text-slate-500 text-center py-3">
              {t("polarChatLoadPrompt")}
            </p>
          )}
          {messages.map((m, i) => <PolarChatBubble key={i} role={m.role} content={m.content} />)}
          {chatLoading && (
            <div className="flex justify-start mb-1.5">
              <div className="bg-slate-700/60 border border-slate-600/40 px-3 py-2 rounded-xl rounded-bl-none">
                <Loader2 size={11} className="animate-spin text-blue-400" />
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="border-t border-slate-700/50 px-3 py-2 flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={polarData ? t("polarChatAskPlaceholder") : t("polarChatLoadFirst")}
            disabled={!polarData}
            rows={1}
            className="flex-1 bg-transparent text-xs text-white placeholder-slate-500 resize-none
              focus:outline-none leading-relaxed disabled:opacity-40 overflow-y-auto"
            style={{ maxHeight: "112px" }}
          />
          <button
            onClick={handleSend}
            disabled={!chatInput.trim() || chatLoading || !polarData}
            className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition-all
              ${(!chatInput.trim() || chatLoading || !polarData)
                ? "text-slate-600 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-500 text-white active:scale-95"}`}
          >
            <Send size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Logo image paths (served from /public) ──────────────────────────────── */
const NAVIGUIDE_LOGO = "/logo-naviguide-7479b7aa.png";
const BERRY_LOGO     = "/logo-berry-mappemonde.png";

/* ── File parsers ─────────────────────────────────────────────────────────── */

/** Parse a GeoJSON string → FeatureCollection preserving one Feature per LineString */
function parseGeoJSON(text) {
  const data     = JSON.parse(text);
  const features = [];

  const extract = (geometry, props = {}) => {
    if (!geometry) return;
    switch (geometry.type) {
      case "LineString":
        features.push({
          type: "Feature",
          properties: props,
          geometry: { type: "LineString", coordinates: geometry.coordinates.map(([lon, lat]) => [lon, lat]) },
        });
        break;
      case "MultiLineString":
        geometry.coordinates.forEach((line) =>
          features.push({
            type: "Feature",
            properties: props,
            geometry: { type: "LineString", coordinates: line.map(([lon, lat]) => [lon, lat]) },
          })
        );
        break;
      case "GeometryCollection":
        geometry.geometries.forEach((g) => extract(g, props));
        break;
      default:
        break;
    }
  };

  if (data.type === "FeatureCollection") {
    data.features.forEach((f) => extract(f.geometry, f.properties || {}));
  } else if (data.type === "Feature") {
    extract(data.geometry, data.properties || {});
  } else {
    extract(data);
  }

  return { type: "FeatureCollection", features };
}

/** Parse a KML string → FeatureCollection with one Feature per Placemark LineString */
function parseKML(text) {
  const doc      = new DOMParser().parseFromString(text, "application/xml");
  const features = [];

  // Each <Placemark> that contains a <LineString> becomes one Feature
  doc.querySelectorAll("Placemark").forEach((placemark) => {
    const nameEl = placemark.querySelector("name");
    const name   = nameEl?.textContent?.trim() || "";

    placemark.querySelectorAll("LineString coordinates").forEach((el) => {
      const coords = [];
      el.textContent.trim().split(/\s+/).forEach((pt) => {
        const [lonStr, latStr] = pt.split(",");
        const lon = parseFloat(lonStr);
        const lat = parseFloat(latStr);
        if (!isNaN(lon) && !isNaN(lat)) coords.push([lon, lat]);
      });
      if (coords.length > 0) {
        features.push({
          type: "Feature",
          properties: { name },
          geometry: { type: "LineString", coordinates: coords },
        });
      }
    });
  });

  return { type: "FeatureCollection", features };
}

/** Strip directory path and extension from a filename */
function stemName(filename) {
  return filename
    .replace(/\\/g, "/")
    .split("/")
    .pop()
    .replace(/\.(geojson|kml|json)$/i, "");
}

/* ── Sub-components ───────────────────────────────────────────────────────── */

/* ── BerryCard ────────────────────────────────────────────────────────────── */
/**
 * States:
 *  "berry-active"            – Berry highlighted (default). Click → "import-mode".
 *  "import-mode"             – Shows two import buttons. Berry route still shown.
 *  "file-active"             – Imported file is the active route. Shows Berry mini-btn + filename (highlighted).
 *  "berry-active-file-loaded"– Berry is active route, file is in memory. Shows Berry (highlighted) + filename.
 */
function BerryCard({
  onRouteImport, onRouteSwitchToBerry, isDrawing,
  onDrawStart, onDrawContinue, onDrawFinish, onCustomDelete, canContinueDraw,
  canFinishDraw = true,
}) {
  const { t } = useLang();
  const [cardMode, setCardMode]         = useState("berry-active");
  const [importedGeoJSON, setImportedGeoJSON] = useState(null);
  const [importedName, setImportedName]       = useState(null);
  const [importError, setImportError]         = useState(null);

  const geoJsonRef = useRef(null);
  const kmlRef     = useRef(null);
  const hasCustom  = Boolean(importedGeoJSON);
  const customOn   = cardMode === "file-active";

  const processFile = (file) => {
    setImportError(null);
    const name = stemName(file.name);
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const text    = e.target.result;
        const isKml   = file.name.toLowerCase().endsWith(".kml");
        const geojson = isKml ? parseKML(text) : parseGeoJSON(text);
        if (geojson.features.length === 0) throw new Error(t("noCoordsFound"));
        setImportedGeoJSON(geojson);
        setImportedName(name);
        setCardMode("file-active");
        onRouteImport(geojson);
      } catch (err) {
        setImportError(err.message);
      }
    };
    reader.readAsText(file);
  };

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
    e.target.value = "";
  };

  const activateBerry = () => {
    setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
    onRouteSwitchToBerry();
  };

  const activateCustom = () => {
    if (!importedGeoJSON) return;
    setCardMode("file-active");
    onRouteImport(importedGeoJSON);
  };

  const handleCancelImport = (e) => {
    e.stopPropagation();
    setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
  };

  const handleFinishDrawing = () => {
    const geojson = onDrawFinish();
    if (geojson?.features?.length > 0) {
      setImportedGeoJSON(geojson);
      setImportedName(t("customRoute"));
      setCardMode("file-active");
      onRouteImport(geojson);
    } else {
      setCardMode(hasCustom ? "berry-active-file-loaded" : "berry-active");
    }
  };

  const handleDelete = (e) => {
    e.stopPropagation();
    setImportedGeoJSON(null);
    setImportedName(null);
    setCardMode("berry-active");
    onCustomDelete?.();
    onRouteSwitchToBerry();
  };

  const pillOn  = "flex-1 min-w-0 px-2 py-1.5 rounded-lg text-[10px] font-semibold leading-tight border border-blue-400/60 bg-blue-600/30 text-blue-100";
  const pillOff = "flex-1 min-w-0 px-2 py-1.5 rounded-lg text-[10px] font-semibold leading-tight border border-slate-600/50 bg-slate-800/50 text-slate-400 hover:text-white hover:border-slate-500";

  const switcher = hasCustom ? (
    <div className="flex gap-1 mb-1.5">
      <button type="button" onClick={activateBerry} className={customOn ? pillOff : pillOn} title={t("backToBerry")}>
        {t("berryMappemonde") // pragma: allowlist secret
        }
      </button>
      <button type="button" onClick={activateCustom} className={customOn ? pillOn : pillOff} title={t("showRoute", { name: importedName })}>
        {importedName || t("customRoute")}
      </button>
    </div>
  ) : null;

  if (cardMode === "import-mode" || isDrawing) {
    return (
      <div className="rounded-lg px-2 py-1.5 border border-slate-700/50 bg-slate-800/60">
        {switcher}
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] text-slate-400 font-medium">{t("importOrDraw")}</span>
          {!isDrawing && (
            <button onClick={handleCancelImport} className="text-slate-500 hover:text-slate-300" title={t("cancel")}>
              <X size={12} />
            </button>
          )}
        </div>
        <div className="flex gap-1.5 mb-1.5">
          <button
            onClick={() => geoJsonRef.current?.click()}
            className="flex-1 flex items-center justify-center gap-1 bg-blue-600/20 hover:bg-blue-600/40
              border border-blue-500/40 rounded-lg px-1.5 py-1.5 text-[10px] text-blue-300 font-medium"
          >
            <Upload size={11} /> GeoJSON
          </button>
          <button
            onClick={() => kmlRef.current?.click()}
            className="flex-1 flex items-center justify-center gap-1 bg-teal-600/20 hover:bg-teal-600/40
              border border-teal-500/40 rounded-lg px-1.5 py-1.5 text-[10px] text-teal-300 font-medium"
          >
            <Upload size={11} /> KML
          </button>
        </div>
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
            onClick={() => onDrawStart()}
            className="w-full flex items-center justify-center gap-1.5 bg-violet-600/20 hover:bg-violet-600/40
              border border-violet-500/40 rounded-lg px-2 py-1.5 text-[10px] text-violet-300 font-medium"
          >
            <Pencil size={11} /> {t("drawOwnRoute")}
          </button>
        )}
        {importError && <p className="text-[10px] text-red-400 mt-1">{importError}</p>}
        <input ref={geoJsonRef} type="file" accept=".geojson,.json" className="hidden" onChange={handleFileChange} />
        <input ref={kmlRef} type="file" accept=".kml" className="hidden" onChange={handleFileChange} />
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
            onClick={() => { setCardMode("import-mode"); (canContinueDraw ? onDrawContinue : onDrawStart)?.(); }}
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

  // berry-active ou berry-active-file-loaded
  return (
    <div className="rounded-lg px-2 py-1.5 border border-blue-500/70 bg-blue-950/30">
      {switcher}
      {!hasCustom && (
        <button
          onClick={() => setCardMode("import-mode")}
          title={t("clickToImport")}
          className="w-full flex items-center gap-2 rounded-lg px-1.5 py-1
            hover:bg-blue-900/30 cursor-pointer"
        >
          <img src={BERRY_LOGO} alt="Berry-Mappemonde"
            className="h-7 w-auto object-contain rounded flex-shrink-0" style={{ maxWidth: 48 }} />
          <div className="text-white font-bold text-[11px] leading-tight tracking-wide">{t("berryMappemonde") /* pragma: allowlist secret */}</div>
        </button>
      )}
      {hasCustom && (
        <button
          onClick={() => setCardMode("import-mode")}
          className="w-full text-[10px] text-slate-400 hover:text-white py-0.5"
        >
          {t("clickNewImport")}
        </button>
      )}
    </div>
  );
}

/* ── Main component ───────────────────────────────────────────────────────── */

export function Sidebar({
  plan, open, onToggle, onRouteImport, onRouteSwitchToBerry, isDrawing,
  onDrawStart, onDrawContinue, onDrawFinish, onCustomDelete, canContinueDraw,
  canFinishDraw,
  isCockpit, polarData, maritimeLayers, simulationMode, onSimulationToggle,
  legContext, onNext, canNext, onPrev, canPrev, briefingLoading,
}) {
  const { t } = useLang();
  const briefing = plan?.executive_briefing || "";

  return (
    <>
      {/*
        Toggle button.
        Offshore: larger (w-12 h-12, brighter border) for gloved use.
        Normal:   w-9 h-9.
      */}
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

      {/* Sidebar panel */}
      <div
        className={`naviguide-sidebar-panel absolute top-0 left-0 h-full z-20 flex flex-col bg-slate-900/97
          shadow-2xl transition-transform duration-300 border-r border-slate-700/60
          ${open ? "translate-x-0" : "-translate-x-full"}`}
        style={{ width: 320 }}
      >

        {/* ── Brand header ─────────────────────────────────────────────── */}
        <div className="px-3 pt-2 pb-2 border-b border-slate-700/60 flex-shrink-0">
          <div className="flex items-center gap-2 mb-1.5">
            <img src={NAVIGUIDE_LOGO} alt="NAVIGUIDE"
              className="h-10 w-10 object-contain rounded-full drop-shadow" />
            <span className="text-white font-bold text-xs tracking-widest">NAVIGUIDE</span>
          </div>

          <BerryCard
            onRouteImport={onRouteImport}
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
                const active  = maritimeLayers[showKey];
                const loading = maritimeLayers[loadingKey];
                const error   = maritimeLayers[errorKey];
                const label   = t(labelKey);
                const title   = error ? `${t(titleKey)} : ${error}` : t(titleKey);
                return (
                  <button
                    key={key}
                    onClick={() => maritimeLayers[toggleKey]((v) => !v)}
                    title={title}
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
                      : <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: active ? color : "transparent", border: `1.5px solid ${error ? "#ef4444" : color}` }} />
                    }
                    {label}
                  </button>
                );
              })}
            </div>
          )}

          {onSimulationToggle && !isDrawing && (
            <button
              onClick={onSimulationToggle}
              title={simulationMode ? t("exitSimulation") : t("simulationModeTooltip")}
              className={[
                "flex items-center justify-center gap-1.5 w-full mt-1.5 px-2 py-1 rounded-lg",
                "text-[10px] font-semibold transition-all duration-150 select-none border",
                simulationMode
                  ? "bg-blue-600/80 text-white border-blue-500/60"
                  : "bg-slate-800/40 text-white/50 border-white/8 hover:text-white/80 hover:bg-slate-700/50",
              ].join(" ")}
            >
              {simulationMode
                ? <><Square size={9} className="fill-current" /><span>{t("exitSimulationShort")}</span></>
                : <><Play  size={9} className="fill-current" /><span>{t("simulationModeLabel")}</span></>
              }
            </button>
          )}
        </div>

        {/*
          ── Stats grid ───────────────────────────────────────────────────
          COCKPIT: always visible even without plan (shows dashes).
          ONBOARDING: only appears once the AI plan has loaded.
        */}
        {/* ── Scrollable content (everything below logos) ────────────────── */}
        <div className="flex-1 overflow-y-auto sidebar-scroll px-4 py-3 space-y-4">

          {/* ── Mode Simulation — panneau métriques + agents IA ─────────── */}
          {simulationMode && (
            <>
              <SimulationPanel
                legContext={legContext}
                onClose={onSimulationToggle}
                onPrev={onPrev}
                canPrev={canPrev}
                onNext={onNext}
                canNext={canNext}
              />
              <AgentPanel
                legContext={legContext}
                language={t ? (t("_lang") === "fr" ? "fr" : "en") : "fr"}
              />
            </>
          )}

          {!isCockpit && !plan && !briefingLoading && !isDrawing && (
            <div className="rounded-xl border border-blue-700/30 bg-blue-950/20 p-3">
              <div className="text-xs font-semibold text-blue-300 mb-1.5 flex items-center gap-1.5">
                {t("gettingStarted")}
              </div>
              <p className="text-xs text-slate-400 leading-relaxed">
                {t("gettingStartedText")}
              </p>
            </div>
          )}

          {/* Polar Chat — always shown above briefing */}
          <PolarChatSection polarData={polarData} />

          {/*
            AI Skipper Briefing.
            COCKPIT: always visible — shows placeholder when not yet loaded.
            ONBOARDING: shown only when plan data is available.
          */}
          {isDrawing && (
            <div>
              <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Shield size={12} className="text-blue-400" />
                {t("briefing")}
              </div>
              <div className="bg-slate-800/50 rounded-xl p-3 border border-slate-700/50">
                <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-line">
                  {t("briefingDrawHint")}
                </p>
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
                  {briefingLoading ? t("briefingLoading") : (briefing || t("briefingPlaceholder"))}
                </p>
              </div>
            </div>
          )}

        </div>
      </div>
    </>
  );
}
