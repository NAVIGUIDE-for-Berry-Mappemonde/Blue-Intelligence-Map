import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Zap } from "lucide-react";
import api from "../../api";
import AgentConsole from "../AgentConsole";
import RunJournalViewer, { pickJournalRunId } from "./RunJournal";

const STATUS_COLORS = {
  SUCCESS: "text-bio",
  MERGED: "text-bio",
  FAILED: "text-alert",
  REJECTED: "text-amberx",
  DUPLICATE: "text-slate-400",
};

const RUN_STATUS = {
  projects: "/swarm/status",
  marinas: "/marinas/build/status",
  capitaineries: "/capitaineries/build/status",
  science: "/science/build/status",
  amp: "/amp/discover-visit-urls/status",
};

export default function JournalPanel({ t, mode, status }) {
  const [stats, setStats] = useState({ total_extractions: 0, success_rate: 0, projects_mapped: 0, items_mapped: 0 });
  const [telemetry, setTelemetry] = useState([]);
  const [failed, setFailed] = useState([]);
  const [forcing, setForcing] = useState({});
  const [runStatus, setRunStatus] = useState(null);
  const [journalRunId, setJournalRunId] = useState(null);

  const load = useCallback(async () => {
    try {
      const reqs = [
        api.get("/stats", { params: { mode: mode || "projects" } }),
        api.get("/telemetry", { params: { mode: mode || "projects" } }),
        api.get("/failed", { params: { mode: mode || "projects" } }),
      ];
      const runUrl = RUN_STATUS[mode];
      if (runUrl) reqs.push(api.get(runUrl));
      const [s, tm, f, run] = await Promise.all(reqs);
      setStats(s.data);
      setTelemetry(tm.data);
      setFailed(f.data);
      if (run) setRunStatus(run.data);
      if ((mode || "projects") === "projects") {
        const liveId = run?.data?.run_id || status?.run_id;
        if (liveId) {
          setJournalRunId(liveId);
        } else {
          try {
            const { data } = await api.get("/projects/runs");
            setJournalRunId(pickJournalRunId(data));
          } catch (_) { /* ignore */ }
        }
      }
    } catch (e) { /* transient */ }
  }, [mode, status?.run_id]);

  useEffect(() => {
    load();
    const i = setInterval(load, 5000);
    return () => clearInterval(i);
  }, [load]);

  const forceOne = async (id) => {
    setForcing((f) => ({ ...f, [id]: true }));
    try { await api.post(`/failed/${id}/force`); } catch (e) { alert(e.response?.data?.detail || e.message); }
  };
  const forceAll = async () => {
    try { await api.post("/failed/force-all"); } catch (e) { alert(e.response?.data?.detail || e.message); }
  };

  return (
    <div className="space-y-4" data-testid="console-journal-panel">
      {(status?.running || (status?.agents || []).length > 0) && (
        <div className="border border-line bg-surface overflow-hidden">
          <AgentConsole t={t} agents={status?.agents || []} />
        </div>
      )}
      {(mode || "projects") === "projects" && (
        <div className="border border-line bg-surface p-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-400 mb-2">{t("consoleTabJournal")}</p>
          <RunJournalViewer t={t} runId={journalRunId || status?.run_id} />
        </div>
      )}
      <div className="grid grid-cols-3 gap-px bg-line border border-line" data-testid="journal-run-kpis">
        <div className="bg-surface p-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">{t("journalRead")}</p>
          <p data-testid="kpi-run-read" className="font-heading font-black text-3xl text-sonar mt-1">
            {runStatus?.summary?.fetched_raw ?? runStatus?.summary?.fetched ?? runStatus?.progress ?? 0}
          </p>
        </div>
        <div className="bg-surface p-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">{t("journalInserted")}</p>
          <p data-testid="kpi-run-inserted" className="font-heading font-black text-3xl text-bio mt-1">
            +{runStatus?.summary?.inserted ?? 0}
          </p>
        </div>
        <div className="bg-surface p-4">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">{t("journalUpdated")}</p>
          <p data-testid="kpi-run-updated" className="font-heading font-black text-3xl text-white mt-1">
            ~{runStatus?.summary?.updated ?? 0}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-px bg-line border border-line">
        <div className="bg-surface p-3">
          <p className="font-mono text-[9px] uppercase text-slate-500">{t("journalUnlocated")}</p>
          <p className="font-heading font-bold text-lg">{runStatus?.summary?.unlocated ?? runStatus?.summary?.unnamed ?? 0}</p>
        </div>
        <div className="bg-surface p-3">
          <p className="font-mono text-[9px] uppercase text-slate-500">{t("journalErrors")}</p>
          <p className="font-heading font-bold text-lg text-alert">{runStatus?.summary?.errors ?? (runStatus?.error ? 1 : 0)}</p>
        </div>
        <div className="bg-surface p-3">
          <p className="font-mono text-[9px] uppercase text-slate-500">{t("itemsMapped")}</p>
          <p data-testid="kpi-projects-mapped" className="font-heading font-bold text-lg">{stats.items_mapped ?? stats.projects_mapped}</p>
        </div>
      </div>
      <p className="font-mono text-[9px] text-slate-500">{t("journalTelemetryHint")}</p>
      <div className="grid grid-cols-2 gap-px bg-line border border-line">
        <div className="bg-surface p-3">
          <p className="font-mono text-[9px] uppercase text-slate-500">{t("totalExtractions")}</p>
          <p data-testid="kpi-total-extractions" className="font-heading font-bold text-lg text-slate-400">{stats.total_extractions}</p>
        </div>
        <div className="bg-surface p-3">
          <p className="font-mono text-[9px] uppercase text-slate-500">{t("successRate")}</p>
          <p data-testid="kpi-success-rate" className="font-heading font-bold text-lg text-slate-400">{stats.success_rate}%</p>
        </div>
      </div>
      {telemetry.length > 0 && (
        <div className="border border-line bg-surface">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-line">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-400">{t("telemetry")}</p>
            <button onClick={load} className="text-slate-500 hover:text-sonar"><RefreshCw size={13} /></button>
          </div>
          <div className="overflow-x-auto max-h-[340px] overflow-y-auto">
            <table className="w-full text-left" data-testid="telemetry-table">
              <thead className="sticky top-0 bg-raised">
                <tr className="font-mono text-[10px] uppercase text-slate-500">
                  <th className="px-4 py-2">{t("targetUrl")}</th>
                  <th className="px-4 py-2">{t("engine")}</th>
                  <th className="px-4 py-2">{t("statusCol")}</th>
                  <th className="px-4 py-2">{t("duration")}</th>
                  <th className="px-4 py-2">{t("results")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50">
                {telemetry.map((r) => (
                  <tr key={r.id} className="hover:bg-raised/50">
                    <td className="px-4 py-2 font-mono text-[11px] text-slate-300 max-w-[340px] truncate" title={r.url}>{r.url}</td>
                    <td className="px-4 py-2 font-mono text-[11px] text-sonar">{r.engine}</td>
                    <td className={`px-4 py-2 font-mono text-[11px] font-bold ${STATUS_COLORS[r.status] || "text-slate-300"}`}>{r.status}</td>
                    <td className="px-4 py-2 font-mono text-[11px] text-slate-400">{(r.duration_ms / 1000).toFixed(1)}s</td>
                    <td className="px-4 py-2 font-mono text-[11px] text-slate-300">{r.results}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {failed.length > 0 && (
        <div className="border border-line bg-surface">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-line">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-400">
              {t("failedTitle")} <span className="text-alert">({failed.length})</span>
            </p>
            <button data-testid="force-all-btn" onClick={forceAll}
              className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold border border-sonar/50 text-sonar rounded-sm hover:bg-sonar/10">
              <Zap size={12} /> {t("forceAll")}
            </button>
          </div>
          <div className="divide-y divide-line/50 max-h-[300px] overflow-y-auto">
            {failed.map((f) => (
              <div key={f.id} className="px-4 py-2.5 flex items-center gap-3 hover:bg-raised/50">
                <div className="flex-1 min-w-0">
                  <p className="font-mono text-[11px] text-slate-300 truncate" title={f.url}>{f.url}</p>
                  <p className="text-[10px] text-slate-500 truncate">
                    <span className="text-amberx uppercase font-mono">{f.stage}</span> — {f.reason}
                  </p>
                </div>
                <button data-testid={`force-extract-btn-${f.id}`} onClick={() => forceOne(f.id)}
                  disabled={forcing[f.id]}
                  className="shrink-0 flex items-center gap-1 px-2.5 py-1 text-[10px] font-semibold border border-sonar/50 text-sonar rounded-sm hover:bg-sonar/10 disabled:opacity-40">
                  <Zap size={10} /> {forcing[f.id] ? "…" : t("forceExtract")}
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
