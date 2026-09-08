import { useEffect, useRef, useState } from "react";
import { Radio, Loader2, PlayCircle, Sparkles, Square } from "lucide-react";
import api from "../../api";
import CardShell from "./CardShell";

export default function CapitaineriesCard({ t }) {
  const [buildStatus, setBuildStatus] = useState(null);
  const [buildStarting, setBuildStarting] = useState(false);
  const [batchStatus, setBatchStatus] = useState(null);
  const [batchStarting, setBatchStarting] = useState(false);
  const [batchCount, setBatchCount] = useState(10);
  const pollRefs = useRef({});

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/capitaineries/build/status");
        if (alive) setBuildStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.build = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.build); };
  }, []);
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/capitaineries/enrich-batch/status");
        if (alive) setBatchStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.batch = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.batch); };
  }, []);

  const startBuild = async () => {
    if (buildStarting || buildStatus?.running) return;
    setBuildStarting(true);
    try { await api.post("/capitaineries/build", { resume: true, clear_before: false }); }
    catch (e) { console.warn("capitaineries build start failed", e); }
    finally { setTimeout(() => setBuildStarting(false), 800); }
  };
  const startBatch = async () => {
    if (batchStarting || batchStatus?.running || buildStatus?.running) return;
    const lim = parseInt(batchCount, 10);
    if (lim === 0 && !window.confirm(t("capitaineriesEnrichAllConfirm"))) return;
    setBatchStarting(true);
    try { await api.post("/capitaineries/enrich-batch", { limit: lim }); }
    catch (e) { console.warn("capitaineries batch start failed", e); }
    finally { setTimeout(() => setBatchStarting(false), 800); }
  };
  const stopBatch = async () => {
    try { await api.post("/capitaineries/enrich-batch/cancel"); }
    catch (e) { console.warn("capitaineries batch cancel failed", e); }
  };

  const shom = buildStatus?.summary?.shom || {};

  return (
    <div data-testid="audit-batch-hub" data-mode-card="capitaineries">
      <CardShell title={t("modeCapitaineries")} icon={<Radio size={13} className="text-accent" />} borderCls="border-accent/40">
        <div>
          <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
            {t("auditCapitaineriesBuild")}
          </label>
          <p className="mb-2 text-[10px] font-mono text-slate-500 leading-relaxed">
            {t("auditCapitaineriesHint")}
          </p>
          <button
            data-testid="audit-capitaineries-scan-btn"
            onClick={startBuild}
            disabled={buildStarting || buildStatus?.running}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-accent/50 bg-accent/10 hover:bg-accent/20 disabled:opacity-70 disabled:cursor-not-allowed text-accent font-semibold text-xs rounded-sm"
          >
            {buildStatus?.running ? (
              <><Loader2 size={13} className="animate-spin" /> {buildStatus.progress}/{buildStatus.total}</>
            ) : (
              <><PlayCircle size={13} /> {t("capitaineriesScan")}</>
            )}
          </button>
          {buildStatus?.summary && !buildStatus.running && (
            <p className="mt-1.5 text-[9px] font-mono text-slate-500 leading-relaxed" data-testid="audit-capitaineries-summary">
              ✓ OSM +{buildStatus.summary.inserted ?? 0} · ~{buildStatus.summary.updated ?? 0}
              {" · "}SHOM +{shom.inserted ?? 0} · fusion {shom.merged ?? 0}
            </p>
          )}
          {buildStatus?.error && !buildStatus.running && (
            <p className="mt-1.5 text-[9px] font-mono text-alert leading-relaxed">
              ✗ {String(buildStatus.error).slice(0, 90)}
            </p>
          )}
          {buildStatus?.running && buildStatus?.logs_tail?.length > 0 && (
            <div className="mt-1.5 text-[9px] font-mono text-slate-500 max-h-16 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1">
              {buildStatus.logs_tail.slice(-4).map((l, i) => <div key={i} className="truncate">{l}</div>)}
            </div>
          )}
        </div>
        <div>
          <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
            {t("auditCapitaineriesEnrich")}
          </label>
          <div className="flex gap-2">
            <select
              value={batchCount}
              onChange={(e) => setBatchCount(e.target.value)}
              disabled={batchStatus?.running}
              data-testid="audit-capitaineries-batch-count"
              className="w-16 px-2 py-1.5 bg-raised border border-line rounded-sm text-xs text-slate-100 focus:outline-none focus:border-accent/60 disabled:opacity-60"
            >
              <option value="5">5</option>
              <option value="10">10</option>
              <option value="25">25</option>
              <option value="0">{t("enrichBatchAllOption")}</option>
            </select>
            <button
              data-testid="audit-capitaineries-batch-btn"
              onClick={startBatch}
              disabled={batchStarting || batchStatus?.running || buildStatus?.running}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-1.5 border border-accent/40 bg-accent/10 hover:bg-accent/20 disabled:opacity-60 disabled:cursor-not-allowed text-accent font-semibold text-xs rounded-sm"
            >
              {batchStatus?.running ? (
                <><Loader2 size={12} className="animate-spin" /> {batchStatus.progress}/{batchStatus.total}</>
              ) : (
                <><Sparkles size={12} /> {t("enrichBatchStart")}</>
              )}
            </button>
            {batchStatus?.running && (
              <button
                data-testid="audit-capitaineries-batch-stop-btn"
                onClick={stopBatch}
                disabled={batchStatus?.cancelling}
                className="flex items-center justify-center gap-1.5 px-3 py-1.5 border border-accent bg-accent/25 hover:bg-accent/40 disabled:opacity-60 text-accent font-bold text-xs rounded-sm"
              >
                <Square size={11} /> {batchStatus?.cancelling ? "…" : "Stop"}
              </button>
            )}
          </div>
          {batchStatus?.running && batchStatus?.logs_tail?.length > 0 && (
            <div
              data-testid="audit-capitaineries-batch-logs"
              className="mt-2 text-[9px] font-mono text-slate-500 max-h-32 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1"
            >
              {batchStatus.logs_tail.slice(-8).map((l, i) => (
                <div key={i} className="truncate">{l}</div>
              ))}
            </div>
          )}
        </div>
      </CardShell>
    </div>
  );
}
