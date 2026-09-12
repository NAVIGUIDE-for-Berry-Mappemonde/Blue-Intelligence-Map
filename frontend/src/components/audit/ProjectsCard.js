import { useState } from "react";
import { Play, Square } from "lucide-react";
import api from "../../api";
import { invalidateRuns } from "../../lib/runCache";

export default function ProjectsCard({ t, status, refresh, rulesPayload }) {
  const [swarmMode, setSwarmMode] = useState("test");
  const [busy, setBusy] = useState(false);
  const [lastRun, setLastRun] = useState(null);
  const running = status?.running;
  const runId = status?.run_id || lastRun?.run_id;

  const deploy = async () => {
    setBusy(true);
    try {
      const extra = rulesPayload ? rulesPayload() : {};
      const { data } = await api.post("/projects/runs", { mode: swarmMode, ...extra });
      setLastRun(data);
      invalidateRuns("projects");
      refresh && refresh();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };
  const stop = async () => {
    setBusy(true);
    try {
      if (runId) {
        await api.post(`/projects/runs/${runId}/cancel`);
      } else {
        await api.post("/swarm/stop");
      }
      refresh && refresh();
    } finally { setBusy(false); }
  };

  return (
    <div className="space-y-3" data-testid="projects-launch">
      <div className="flex items-center gap-2 flex-wrap">
        <span
          data-testid="swarm-status-badge"
          className={`font-mono text-[10px] px-2 py-0.5 rounded-sm border ${running ? "text-bio border-bio/40 bg-bio/5" : "text-slate-400 border-line bg-raised"}`}
        >
          {running ? t("runningStatus") : t("idle")}
        </span>
        <span
          className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${status?.tinyfish ? "text-sonar border-sonar/40" : "text-amberx border-amberx/40"}`}
        >
          {status?.tinyfish ? t("tfActive") : t("tfFallback")}
        </span>
        <span
          className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${status?.llm ? "text-sonar border-sonar/40" : "text-amberx border-amberx/40"}`}
          title={t("llmEngineTooltip")}
        >
          {status?.llm ? (status?.engine || "").toUpperCase() || t("llmActive") : t("llmFallback")}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-px bg-line border border-line">
        <div className="bg-surface p-2">
          <p className="font-mono text-[9px] text-slate-500 uppercase">{t("active")}</p>
          <p data-testid="active-agents-count" className="font-heading font-black text-lg text-sonar">{status?.active ?? 0}</p>
        </div>
        <div className="bg-surface p-2">
          <p className="font-mono text-[9px] text-slate-500 uppercase">{t("queued")}</p>
          <p data-testid="queued-count" className="font-heading font-black text-lg text-slate-200">{status?.queued ?? 0}</p>
        </div>
      </div>

      <div className="flex gap-2">
        <button
          data-testid="mode-test-btn"
          onClick={() => setSwarmMode("test")}
          className={`flex-1 py-1.5 text-xs font-semibold border rounded-sm ${swarmMode === "test" ? "border-sonar/50 bg-sonar/10 text-sonar" : "border-line text-slate-400 hover:bg-raised"}`}
        >{t("modeTest")}</button>
        <button
          data-testid="mode-full-btn"
          onClick={() => setSwarmMode("full")}
          className={`flex-1 py-1.5 text-xs font-semibold border rounded-sm ${swarmMode === "full" ? "border-sonar/50 bg-sonar/10 text-sonar" : "border-line text-slate-400 hover:bg-raised"}`}
        >{t("modeFull")}</button>
      </div>
      <button
        data-testid="deploy-swarm-btn"
        onClick={deploy}
        disabled={busy || running}
        className="w-full flex items-center justify-center gap-2 py-2 font-heading font-bold text-sm rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <Play size={14} /> {t("launchRun")}
      </button>
      <p className="font-mono text-[9px] text-slate-500 leading-relaxed" data-testid="isolated-run-hint">
        {t("isolatedRunHint")}
      </p>
      {runId && (
        <p className="font-mono text-[10px] text-sonar/80" data-testid="project-run-id">
          {t("currentRun")} {runId} · {t("wroteProjectsFalse")}
        </p>
      )}
      <button
        data-testid="stop-swarm-btn"
        onClick={stop}
        disabled={busy || !running}
        className="w-full flex items-center justify-center gap-2 py-1.5 font-semibold text-xs rounded-sm border border-alert/50 text-alert hover:bg-alert/10 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <Square size={12} /> {t("stopSwarm")}
      </button>

      <div className="console-scanlines bg-black/60 border border-line rounded-sm h-32 overflow-y-auto p-2 font-mono text-[10px] leading-relaxed" data-testid="swarm-log-stream">
        {(status?.logs || []).slice(-40).map((l, i) => (
          <div key={i} className={
            l.level === "error" ? "text-alert" :
            l.level === "warn" ? "text-amberx" :
            l.level === "success" ? "text-bio" : "text-sonar/80"
          }>
            <span className="text-slate-600">{l.ts?.slice(11, 19)}</span> {l.msg}
          </div>
        ))}
        {running && <span className="text-bio cursor-blink">▊</span>}
      </div>
    </div>
  );
}
