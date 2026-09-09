import { useEffect, useRef, useState } from "react";
import { Loader2, Play, Radar, Square } from "lucide-react";
import api from "../../api";

export default function FormalitiesCard({ t, onPoeRefresh, rulesPayload }) {
  const [refStatus, setRefStatus] = useState(null);
  const [refStarting, setRefStarting] = useState(false);
  const [autoStatus, setAutoStatus] = useState(null);
  const [poeStarting, setPoeStarting] = useState(false);
  const [poeRuns, setPoeRuns] = useState([]);
  const [activeIds, setActiveIds] = useState([]);
  const pollRefs = useRef({});
  const extra = () => (rulesPayload ? rulesPayload() : {});

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
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/poe/runs");
        if (!alive) return;
        setPoeRuns(data.items || []);
        setActiveIds(data.active_run_ids || []);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.poeRuns = setInterval(check, 4000);
    return () => { alive = false; clearInterval(pollRefs.current.poeRuns); };
  }, []);

  const startPoeReferential = async () => {
    if (refStarting || refStatus?.running) return;
    setRefStarting(true);
    try { await api.post("/poe/referential/build"); }
    catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setTimeout(() => setRefStarting(false), 800); }
  };

  const resumable = (poeRuns || []).find((r) => r.state === "running" || r.id === activeIds[0] || r._id === activeIds[0]);
  const lastIncomplete = (poeRuns || []).find((r) => r.state && !["done", "cancelled", "failed"].includes(r.state));

  const startPoeRun = async () => {
    if (poeStarting) return;
    setPoeStarting(true);
    try {
      await api.post("/poe/runs", { variant: "tinyfish", ...extra() });
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setTimeout(() => setPoeStarting(false), 800); }
  };
  const resumePoeRun = async () => {
    const rid = lastIncomplete?.id || lastIncomplete?._id;
    if (!rid || poeStarting) return;
    setPoeStarting(true);
    try {
      await api.post("/poe/runs", { resume_run_id: rid });
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setTimeout(() => setPoeStarting(false), 800); }
  };
  const stopPoeRun = async () => {
    const rid = activeIds[0] || resumable?.id || resumable?._id;
    if (!rid) return;
    try { await api.post(`/poe/runs/${rid}/cancel`); }
    catch (e) { alert(e.response?.data?.detail || e.message); }
  };

  const poeRunning = activeIds.length > 0;

  return (
    <div className="space-y-3" data-testid="formalities-launch">
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

      <div className="pt-3 border-t border-line space-y-2" data-testid="poe-run-launch">
        <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block">
          {t("poeRunLaunch")}
        </label>
        <p className="font-mono text-[9px] text-slate-500 leading-relaxed">{t("isolatedRunHintLive")}</p>
        {(activeIds[0] || lastIncomplete) && (
          <p className="font-mono text-[10px] text-amberx/80" data-testid="poe-run-id">
            {t("currentRun")} {activeIds[0] || lastIncomplete?.id || lastIncomplete?._id}
          </p>
        )}
        <div className="flex gap-2">
          <button
            data-testid="poe-run-start-btn"
            onClick={startPoeRun}
            disabled={poeStarting || poeRunning}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 border border-amberx/50 bg-amberx/10 hover:bg-amberx/20 disabled:opacity-70 text-amberx font-semibold text-xs rounded-sm"
          >
            {poeRunning || poeStarting
              ? <><Loader2 size={13} className="animate-spin" /> {t("runningStatus")}</>
              : <><Play size={13} /> {t("poeRunStart")}</>}
          </button>
          {lastIncomplete && !poeRunning && (
            <button
              data-testid="poe-run-resume-btn"
              onClick={resumePoeRun}
              disabled={poeStarting}
              className="px-3 py-2 border border-amberx/40 text-amberx text-xs font-semibold rounded-sm hover:bg-amberx/10"
            >
              {t("poeRunResume")}
            </button>
          )}
          {poeRunning && (
            <button
              data-testid="poe-run-stop-btn"
              onClick={stopPoeRun}
              className="px-3 py-2 border border-alert/50 text-alert rounded-sm hover:bg-alert/10"
            >
              <Square size={13} />
            </button>
          )}
        </div>
      </div>

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
    </div>
  );
}
