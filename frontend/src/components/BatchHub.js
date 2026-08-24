import { useEffect, useRef, useState } from "react";
import { Anchor, Compass, Loader2, PlayCircle, ScrollText, Sparkles } from "lucide-react";
import api from "../api";

/**
 * BatchHub — Phase 5 tri-mode audit block.
 *
 * Regroups the batch triggers previously living in the Marinas / Formalities
 * sidebars. Each block owns:
 *   - Its "start" button
 *   - Its running progress bar / counter
 *   - A live log tail (last 8 lines)
 *
 * Unit-level actions (per-marina "Enrich", per-fiche "Refresh") stay in the
 * sidebars — only the *batch* triggers moved here.
 */
export default function BatchHub({ t, onFormalitiesRefresh }) {
  // Marinas — build
  const [buildStatus, setBuildStatus] = useState(null);
  const [buildStarting, setBuildStarting] = useState(false);
  // Marinas — enrich batch
  const [marinaBatchStatus, setMarinaBatchStatus] = useState(null);
  const [marinaBatchStarting, setMarinaBatchStarting] = useState(false);
  const [marinaBatchCount, setMarinaBatchCount] = useState(10);
  // Formalities — batch
  const [formalitiesBatchStatus, setFormalitiesBatchStatus] = useState(null);
  const [formalitiesBatchStarting, setFormalitiesBatchStarting] = useState(false);

  const pollRefs = useRef({});

  // Marinas build poll
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/marinas/build/status");
        if (alive) setBuildStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.build = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.build); };
  }, []);

  // Marinas enrich batch poll
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/marinas/enrich-batch/status");
        if (alive) setMarinaBatchStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.marinasBatch = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.marinasBatch); };
  }, []);

  // Formalities batch poll
  useEffect(() => {
    let alive = true;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/formalities/generate-batch/status");
        if (!alive) return;
        setFormalitiesBatchStatus(data);
        if (data.running || (wasRunning && !data.running)) {
          if (onFormalitiesRefresh) onFormalitiesRefresh();
        }
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.formalitiesBatch = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.formalitiesBatch); };
  }, [onFormalitiesRefresh]);

  // ---- Kick actions ----
  const startBuild = async () => {
    if (buildStarting || buildStatus?.running) return;
    setBuildStarting(true);
    try {
      await api.post("/marinas/build", { include_corridor: false, clear_before: false });
    } catch (e) {
      console.warn("build start failed", e);
    } finally {
      setTimeout(() => setBuildStarting(false), 800);
    }
  };
  const startMarinaBatch = async () => {
    if (marinaBatchStarting || marinaBatchStatus?.running || buildStatus?.running) return;
    setMarinaBatchStarting(true);
    try {
      await api.post("/marinas/enrich-batch", { limit: parseInt(marinaBatchCount, 10) });
    } catch (e) {
      console.warn("marina batch start failed", e);
    } finally {
      setTimeout(() => setMarinaBatchStarting(false), 800);
    }
  };
  const startFormalitiesBatch = async () => {
    if (formalitiesBatchStarting || formalitiesBatchStatus?.running) return;
    if (!window.confirm(t("formalitiesBatchConfirm"))) return;
    setFormalitiesBatchStarting(true);
    try {
      await api.post("/formalities/generate-batch");
    } catch (e) {
      console.warn("formalities batch start failed", e);
    } finally {
      setTimeout(() => setFormalitiesBatchStarting(false), 800);
    }
  };

  const modeCard = (title, icon, bodyClass, children, accentClass) => (
    <div className={`border border-line bg-surface ${accentClass}`}>
      <div className="px-4 py-2.5 border-b border-line flex items-center gap-2">
        {icon}
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-400">{title}</p>
      </div>
      <div className={`p-4 space-y-3 ${bodyClass}`}>{children}</div>
    </div>
  );

  return (
    <div data-testid="audit-batch-hub" className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* ---- Projects (Swarm status only for now; SwarmControls stays above) ---- */}
      {modeCard(
        t("modeProjects"),
        <Compass size={14} className="text-sonar" />,
        "",
        <div className="text-[11px] text-slate-400 leading-relaxed">
          {t("auditProjectsHint")}
        </div>,
        "border-l-2 border-l-sonar/50",
      )}

      {/* ---- Marinas — build + enrich batch ---- */}
      {modeCard(
        t("modeMarinas"),
        <Anchor size={14} className="text-alert" />,
        "",
        <>
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("auditMarinasBuild")}
            </label>
            <button
              data-testid="audit-marinas-scan-btn"
              onClick={startBuild}
              disabled={buildStarting || buildStatus?.running}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-alert/50 bg-alert/10 hover:bg-alert/20 disabled:opacity-70 disabled:cursor-not-allowed text-alert font-semibold text-xs rounded-sm"
            >
              {buildStatus?.running ? (
                <><Loader2 size={13} className="animate-spin" /> {buildStatus.progress}/{buildStatus.total}</>
              ) : (
                <><PlayCircle size={13} /> {t("marinasScan")}</>
              )}
            </button>
            {buildStatus?.summary && !buildStatus.running && (
              <p className="mt-1.5 text-[9px] font-mono text-slate-500 leading-relaxed">
                ✓ OSM {buildStatus.summary.by_source?.openstreetmap ?? 0} · SHOM {buildStatus.summary.by_source?.shom ?? 0} · Curated {buildStatus.summary.by_source?.curated ?? 0}
              </p>
            )}
          </div>
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("auditMarinasEnrich")}
            </label>
            <div className="flex gap-2">
              <select
                value={marinaBatchCount}
                onChange={(e) => setMarinaBatchCount(e.target.value)}
                disabled={marinaBatchStatus?.running}
                data-testid="audit-marinas-batch-count"
                className="w-16 px-2 py-1.5 bg-raised border border-line rounded-sm text-xs text-slate-100 focus:outline-none focus:border-alert/60 disabled:opacity-60"
              >
                <option value="5">5</option>
                <option value="10">10</option>
                <option value="25">25</option>
              </select>
              <button
                data-testid="audit-marinas-batch-btn"
                onClick={startMarinaBatch}
                disabled={marinaBatchStarting || marinaBatchStatus?.running || buildStatus?.running}
                className="flex-1 flex items-center justify-center gap-2 px-3 py-1.5 border border-alert/40 bg-alert/10 hover:bg-alert/20 disabled:opacity-60 disabled:cursor-not-allowed text-alert font-semibold text-xs rounded-sm"
              >
                {marinaBatchStatus?.running ? (
                  <><Loader2 size={12} className="animate-spin" /> {marinaBatchStatus.progress}/{marinaBatchStatus.total}</>
                ) : (
                  <><Sparkles size={12} /> {t("enrichBatchStart")}</>
                )}
              </button>
            </div>
            {marinaBatchStatus?.results && marinaBatchStatus.results.length > 0 && (
              <div className="mt-2 text-[9px] font-mono max-h-24 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1">
                {marinaBatchStatus.results.slice(-6).map((r, i) => (
                  <div key={i} className="truncate text-slate-400">
                    <span className={r.enriched ? "text-bio" : (r.error ? "text-alert" : "text-slate-500")}>
                      {r.enriched ? "✓" : r.error ? "✗" : "·"}
                    </span> {r.name}
                    {r.source && <span className="text-slate-500"> · {r.source}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>,
        "border-l-2 border-l-alert/50",
      )}

      {/* ---- Formalities — generate batch ---- */}
      {modeCard(
        t("modeFormalities"),
        <ScrollText size={14} className="text-amberx" />,
        "",
        <>
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("auditFormalitiesBatch")}
            </label>
            <button
              data-testid="audit-formalities-batch-btn"
              onClick={startFormalitiesBatch}
              disabled={formalitiesBatchStarting || formalitiesBatchStatus?.running}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-amberx/50 bg-amberx/10 hover:bg-amberx/20 disabled:opacity-70 disabled:cursor-not-allowed text-amberx font-semibold text-xs rounded-sm"
            >
              {formalitiesBatchStatus?.running ? (
                <><Loader2 size={13} className="animate-spin" /> {formalitiesBatchStatus.progress ?? 0}/{formalitiesBatchStatus.total ?? 13}</>
              ) : (
                <><Sparkles size={13} /> {t("formalitiesBatchStart")}</>
              )}
            </button>
          </div>
          {formalitiesBatchStatus?.logs_tail && formalitiesBatchStatus.logs_tail.length > 0 && (
            <div
              data-testid="audit-formalities-batch-logs"
              className="text-[9px] font-mono text-slate-500 max-h-32 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1"
            >
              {formalitiesBatchStatus.logs_tail.slice(-8).map((l, i) => (
                <div key={i} className="truncate">{l}</div>
              ))}
            </div>
          )}
          {formalitiesBatchStatus?.results && formalitiesBatchStatus.results.length > 0 && (
            <div className="text-[9px] font-mono text-slate-400 max-h-24 overflow-y-auto leading-relaxed">
              {formalitiesBatchStatus.results.slice(-8).map((r, i) => (
                <div key={i} className="truncate">
                  <span className={r.status === "ia" ? "text-bio" : r.status === "verifiee" ? "text-bio" : r.status === "ia_sans_source" ? "text-amberx" : "text-slate-500"}>
                    ●
                  </span> {r.territory_code} · {r.status || r.error?.slice(0, 40) || "?"}
                </div>
              ))}
            </div>
          )}
        </>,
        "border-l-2 border-l-amberx/50",
      )}
    </div>
  );
}
