import { useEffect, useRef, useState } from "react";
import { Loader2, Radar, ScrollText } from "lucide-react";
import api from "../../api";
import CardShell from "./CardShell";

/**
 * FormalitiesCard — carte Audit du mode Formalités : référentiel ZEE (VLIZ)
 * et statut du rafraîchissement auto (MD5). Pas de generate-batch.
 */
export default function FormalitiesCard({ t, onPoeRefresh }) {
  const [refStatus, setRefStatus] = useState(null);
  const [refStarting, setRefStarting] = useState(false);
  const [autoStatus, setAutoStatus] = useState(null);
  const pollRefs = useRef({});

  useEffect(() => {
    let alive = true;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/poe/referential/status");
        if (!alive) return;
        setRefStatus(data);
        if (wasRunning && !data.running && onPoeRefresh) onPoeRefresh();
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.poeRef = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.poeRef); };
  }, [onPoeRefresh]);
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/poe/auto-refresh/status");
        if (alive) setAutoStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.poeAuto = setInterval(check, 20000);
    return () => { alive = false; clearInterval(pollRefs.current.poeAuto); };
  }, []);

  const startPoeReferential = async () => {
    if (refStarting || refStatus?.running) return;
    setRefStarting(true);
    try { await api.post("/poe/referential/build"); }
    catch (e) { console.warn("poe referential start failed", e); }
    finally { setTimeout(() => setRefStarting(false), 800); }
  };

  return (
    <div data-testid="audit-batch-hub" data-mode-card="formalities">
      <CardShell title={t("modeFormalities")} icon={<ScrollText size={13} className="text-amberx" />} borderCls="border-amberx/40">
        {/* --- EEZ referential (VLIZ Marine Regions) --- */}
        <div>
          <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
            {t("poeEezAttribution")}
          </label>
          <button
            data-testid="poe-referential-btn"
            onClick={startPoeReferential}
            disabled={refStarting || refStatus?.running}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-amberx/50 bg-amberx/10 hover:bg-amberx/20 disabled:opacity-70 disabled:cursor-not-allowed text-amberx font-semibold text-xs rounded-sm"
          >
            {refStatus?.running ? (
              <><Loader2 size={13} className="animate-spin" /> {t("auditPoeReferentialRunning")} {refStatus.progress}/{refStatus.total || "?"}</>
            ) : (
              <><Radar size={13} /> {t("auditPoeReferential")}</>
            )}
          </button>
          {refStatus?.running && refStatus?.logs_tail?.length > 0 && (
            <div className="mt-1.5 text-[9px] font-mono text-slate-500 max-h-16 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1" data-testid="poe-referential-logs">
              {refStatus.logs_tail.slice(-4).map((l, i) => <div key={i} className="truncate">{l}</div>)}
            </div>
          )}
          {refStatus?.summary && !refStatus.running && (
            <p className="mt-1.5 text-[9px] font-mono text-slate-500" data-testid="poe-referential-summary">
              ✓ {refStatus.summary.zones} ZEE · map {refStatus.summary.map_file_kb} Ko
            </p>
          )}
          {refStatus?.error && !refStatus.running && (
            <p className="mt-1.5 text-[9px] font-mono text-alert">✗ {String(refStatus.error).slice(0, 100)}</p>
          )}
        </div>

        {/* --- Auto-refresh (MD5 monitoring) --- */}
        <div className="pt-3 border-t border-line" data-testid="poe-auto-refresh-section">
          <div className="flex items-center gap-2 mb-1">
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${autoStatus?.cycle_running ? "bg-amberx animate-pulse" : "bg-bio"}`} />
            <span className="font-mono text-[9px] uppercase tracking-widest text-slate-400">
              ♻ {t("poeAutoRefreshTitle")} · {autoStatus?.cycle_running ? t("poeAutoCycleRunning") : t("poeAutoActive")}
            </span>
          </div>
          <p className="text-[10px] text-slate-500 leading-relaxed">{t("poeAutoRefreshDesc")}</p>
          {autoStatus?.last_summary && (
            <p className="mt-1 font-mono text-[9px] text-slate-500" data-testid="poe-auto-refresh-summary">
              {t("poeAutoLastCycle")}: {autoStatus.last_summary.checked} {t("poeAutoChecked")} ·{" "}
              {autoStatus.last_summary.unchanged_md5} {t("poeAutoUnchangedMd5")} ·{" "}
              {autoStatus.last_summary.updated} {t("poeAutoUpdated")}
              {autoStatus.last_summary.errors_retried > 0 ? ` · ${autoStatus.last_summary.errors_retried} ${t("poeAutoErrRetried")}` : ""}
            </p>
          )}
        </div>
      </CardShell>
    </div>
  );
}
