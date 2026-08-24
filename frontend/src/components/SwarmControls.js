import { useState } from "react";
import { Play, Square } from "lucide-react";
import api from "../api";
import AgentConsole from "./AgentConsole";

export default function SwarmControls({ t, status, refresh }) {
  const [mode, setMode] = useState("test");
  const [clearDb, setClearDb] = useState(false);
  const [forceRescan, setForceRescan] = useState(false);
  const [busy, setBusy] = useState(false);
  const running = status?.running;

  const deploy = async () => {
    setBusy(true);
    try {
      await api.post("/swarm/deploy", { mode, clear_db: clearDb, force_rescan: forceRescan });
      refresh();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const stop = async () => {
    setBusy(true);
    try { await api.post("/swarm/stop"); refresh(); } finally { setBusy(false); }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="swarm-controls">
      {/* Status + deploy */}
      <div className="border border-line bg-surface p-4">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">{t("swarmStatus")}</p>
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <span data-testid="swarm-status-badge" className={`font-mono text-xs px-2 py-0.5 rounded-sm border ${running ? "text-bio border-bio/40 bg-bio/5" : "text-slate-400 border-line bg-raised"}`}>
            {running ? t("runningStatus") : t("idle")}
          </span>
          <span className="font-mono text-xs px-2 py-0.5 rounded-sm border border-line text-slate-300 bg-raised">
            {status?.mode === "full" ? t("modeFull").toUpperCase() : t("modeTest").toUpperCase()}
          </span>
          <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${status?.tinyfish ? "text-sonar border-sonar/40" : "text-amberx border-amberx/40"}`}>
            {status?.tinyfish ? t("tfActive") : t("tfFallback")}
          </span>
          <span className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${status?.llm ? "text-sonar border-sonar/40" : "text-amberx border-amberx/40"}`}
            title={t("llmEngineTooltip")}
          >
            {status?.llm ? (status?.engine || "").toUpperCase() || t("llmActive") : t("llmFallback")}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-px bg-line border border-line mb-3">
          <div className="bg-surface p-2">
            <p className="font-mono text-[10px] text-slate-500 uppercase">{t("active")}</p>
            <p data-testid="active-agents-count" className="font-heading font-black text-xl text-sonar">{status?.active ?? 0}</p>
          </div>
          <div className="bg-surface p-2">
            <p className="font-mono text-[10px] text-slate-500 uppercase">{t("queued")}</p>
            <p data-testid="queued-count" className="font-heading font-black text-xl text-slate-200">{status?.queued ?? 0}</p>
          </div>
        </div>
        <div className="flex gap-2 mb-2.5">
          <button
            data-testid="mode-test-btn"
            onClick={() => setMode("test")}
            className={`flex-1 py-1.5 text-xs font-semibold border rounded-sm ${mode === "test" ? "border-sonar/50 bg-sonar/10 text-sonar" : "border-line text-slate-400 hover:bg-raised"}`}
          >{t("modeTest")}</button>
          <button
            data-testid="mode-full-btn"
            onClick={() => setMode("full")}
            className={`flex-1 py-1.5 text-xs font-semibold border rounded-sm ${mode === "full" ? "border-sonar/50 bg-sonar/10 text-sonar" : "border-line text-slate-400 hover:bg-raised"}`}
          >{t("modeFull")}</button>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none mb-2.5">
          <input data-testid="clear-db-checkbox" type="checkbox" checked={clearDb} onChange={(e) => setClearDb(e.target.checked)}
            className="accent-cyan-400" />
          {t("clearBefore")}
        </label>
        <button
          data-testid="deploy-swarm-btn"
          onClick={deploy}
          disabled={busy || running}
          className="w-full flex items-center justify-center gap-2 py-2.5 font-heading font-bold text-sm rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25 hover:shadow-[0_0_18px_rgba(0,240,255,0.25)] disabled:opacity-40 disabled:cursor-not-allowed mb-2"
        >
          <Play size={14} /> {t("deploy")}
        </button>
        <button
          data-testid="stop-swarm-btn"
          onClick={stop}
          disabled={busy || !running}
          className="w-full flex items-center justify-center gap-2 py-2 font-semibold text-xs rounded-sm border border-alert/50 text-alert hover:bg-alert/10 disabled:opacity-30 disabled:cursor-not-allowed mb-3"
        >
          <Square size={12} /> {t("stopSwarm")}
        </button>
        <div className="console-scanlines bg-black/60 border border-line rounded-sm h-36 overflow-y-auto p-2 font-mono text-[10px] leading-relaxed" data-testid="swarm-log-stream">
          {(status?.logs || []).slice(-60).map((l, i) => (
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

      {/* Live agent console */}
      <div className="border border-line bg-surface overflow-hidden">
        <AgentConsole t={t} agents={status?.agents || []} />
      </div>
    </div>
  );
}
