import { useEffect, useState } from "react";
import { Check, Compass, Play, Square } from "lucide-react";
import api from "../../api";
import CardShell, { smallInput } from "./CardShell";

/**
 * ProjectsCard — carte Audit du mode Projets : pilotage du swarm (Test/Full,
 * Clear DB, Deploy/Stop, logs), réglages d'extraction exclusifs au swarm et
 * filtrage marin. Tous les appels LLM passent par OpenRouter (modèle défini
 * côté serveur via OPENROUTER_MODEL).
 */
export default function ProjectsCard({ t, status, refresh, settings, onSettingsSaved }) {
  const [swarmMode, setSwarmMode] = useState("test");
  const [busy, setBusy] = useState(false);
  const running = status?.running;
  // Extraction + marine filtering settings form
  const [form, setForm] = useState(null);
  const [savedFlag, setSavedFlag] = useState(false);

  useEffect(() => {
    if (settings) {
      setForm((f) => f || {
        tinyfish_agents: settings.tinyfish_agents,
        extract_concurrency: settings.extract_concurrency,
        follow_the_money: !!settings.follow_the_money,
        max_partner_orgs: settings.max_partner_orgs,
        saturation_limit: settings.saturation_limit,
        rescan_after_days: settings.rescan_after_days,
        // Phase 7 — marine filtering migrated here
        max_coast_km: settings.max_coast_km,
        min_marine_score: settings.min_marine_score,
      });
    }
  }, [settings]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const deploy = async () => {
    setBusy(true);
    try {
      await api.post("/swarm/deploy", { mode: swarmMode, clear_db: false });
      refresh && refresh();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };
  const stop = async () => {
    setBusy(true);
    try { await api.post("/swarm/stop"); refresh && refresh(); } finally { setBusy(false); }
  };
  const saveExtraction = async () => {
    if (!form) return;
    const body = { ...form };
    ["tinyfish_agents", "extract_concurrency", "max_partner_orgs", "saturation_limit"].forEach(
      (k) => { body[k] = parseInt(body[k], 10) || undefined; });
    body.rescan_after_days = parseFloat(body.rescan_after_days);
    body.max_coast_km = parseFloat(body.max_coast_km);
    body.min_marine_score = parseFloat(body.min_marine_score);
    try {
      await api.put("/settings", body);
      setSavedFlag(true);
      setTimeout(() => setSavedFlag(false), 2000);
      onSettingsSaved && onSettingsSaved();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    }
  };

  return (
    <div data-testid="audit-batch-hub" data-mode-card="projects">
      <CardShell title={t("modeProjects")} icon={<Compass size={13} className="text-sonar" />} borderCls="border-sonar/40">
        {/* Status pills */}
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
          <Play size={14} /> {t("deploy")}
        </button>
        <button
          data-testid="stop-swarm-btn"
          onClick={stop}
          disabled={busy || !running}
          className="w-full flex items-center justify-center gap-2 py-1.5 font-semibold text-xs rounded-sm border border-alert/50 text-alert hover:bg-alert/10 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <Square size={12} /> {t("stopSwarm")}
        </button>

        {/* Log stream */}
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

        {/* --- Extraction settings + Marine filtering (Phase 7 migrated) --- */}
        {form && (
          <div className="pt-3 mt-2 border-t border-line space-y-2.5" data-testid="audit-extraction-settings">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/80">
              {t("auditExtractionSettingsTitle")}
            </p>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("tinyfishAgents")}</label>
              <select data-testid="tinyfish-agents-select" value={form.tinyfish_agents} onChange={(e) => set("tinyfish_agents", e.target.value)} className={smallInput}>
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">
                {t("concurrency")} ({form.extract_concurrency})
              </label>
              <input data-testid="concurrency-input" type="range" min="1" max="20" value={form.extract_concurrency}
                onChange={(e) => set("extract_concurrency", e.target.value)} className="w-full accent-cyan-400" />
            </div>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("extractionEngine")}</label>
              <div data-testid="extraction-engine-badge" className={`${smallInput} bg-black/30 text-sonar cursor-default`}>
                OpenRouter
              </div>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
              <input data-testid="follow-money-checkbox" type="checkbox" checked={!!form.follow_the_money}
                onChange={(e) => set("follow_the_money", e.target.checked)} className="accent-cyan-400" />
              {t("followMoney")}
            </label>
            {form.follow_the_money && (
              <div>
                <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("maxPartnerOrgs")}</label>
                <input data-testid="max-partner-orgs-input" type="number" min="1" max="20" value={form.max_partner_orgs}
                  onChange={(e) => set("max_partner_orgs", e.target.value)} className={smallInput} />
              </div>
            )}
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("autoStopLimit")}</label>
              <input data-testid="saturation-limit-input" type="number" min="0" max="500" value={form.saturation_limit}
                onChange={(e) => set("saturation_limit", e.target.value)} className={smallInput} />
            </div>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("rescanDays")}</label>
              <input data-testid="rescan-days-input" type="number" min="0" max="365" step="0.5" value={form.rescan_after_days}
                onChange={(e) => set("rescan_after_days", e.target.value)} className={smallInput} />
            </div>

            {/* Phase 7 — Marine filtering (projects-exclusive) */}
            <div className="pt-3 mt-2 border-t border-line space-y-2.5" data-testid="audit-marine-filtering">
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/80">
                {t("marineFiltering")}
              </p>
              <div>
                <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("maxCoastKm")}</label>
                <input data-testid="max-coast-km-input" type="number" value={form.max_coast_km ?? ""}
                  onChange={(e) => set("max_coast_km", e.target.value)} className={smallInput} />
              </div>
              <div>
                <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">
                  {t("minMarineScore")} ({form.min_marine_score ?? "—"})
                </label>
                <input data-testid="min-marine-score-input" type="range" min="0" max="1" step="0.05" value={form.min_marine_score ?? 0}
                  onChange={(e) => set("min_marine_score", e.target.value)} className="w-full accent-cyan-400" />
              </div>
            </div>

            <button
              data-testid="save-swarm-settings-btn"
              onClick={saveExtraction}
              className="w-full flex items-center justify-center gap-2 py-1.5 text-xs font-semibold rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25"
            >
              {savedFlag ? <><Check size={12} /> {t("saved")}</> : t("save")}
            </button>
          </div>
        )}
      </CardShell>
    </div>
  );
}
