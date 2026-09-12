import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import api from "../../api";
import { invalidateRuns } from "../../lib/runCache";
import LaunchScope from "./LaunchScope";

const SOURCE_DEFS = [
  { id: "sextant", labelKey: "scienceSourceSextant" },
  { id: "odatis", labelKey: "scienceSourceOdatis" },
  { id: "edmed", labelKey: "scienceSourceEdmed" },
  { id: "argo", labelKey: "scienceSourceArgo" },
  { id: "csr", labelKey: "scienceSourceCsr" },
];

export default function ScienceCard({ t, rulesPayload }) {
  const [scope, setScope] = useState("test");
  const [buildStatus, setBuildStatus] = useState(null);
  const [starting, setStarting] = useState(false);
  const [sources, setSources] = useState(() => new Set(SOURCE_DEFS.map((s) => s.id)));
  const pollRef = useRef(null);
  const extra = () => (rulesPayload ? rulesPayload() : {});

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/science/build/status");
        if (alive) setBuildStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRef.current = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRef.current); };
  }, []);

  const toggleSource = (id) => {
    setSources((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selected = SOURCE_DEFS.filter((s) => sources.has(s.id));
  const launchLabel = selected.length
    ? `${t("launchRun")} · ${selected.map((s) => t(s.labelKey).split("·")[0].trim()).join(" + ")}`
    : t("launchRun");

  const startBuild = async () => {
    if (starting || buildStatus?.running || sources.size === 0) return;
    setStarting(true);
    try {
      await api.post("/science/build", {
        sources: SOURCE_DEFS.map((s) => s.id).filter((id) => sources.has(id)),
        scope,
        ...extra(),
      });
      invalidateRuns("science");
    } catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setTimeout(() => setStarting(false), 800); }
  };

  const stopBuild = async () => {
    try { await api.post("/science/build/cancel"); }
    catch (e) { console.warn("science build cancel failed", e); }
  };

  const summary = buildStatus?.summary || null;
  const perSource = summary?.sources || {};

  return (
    <div className="space-y-3" data-testid="science-launch">
      <LaunchScope
        t={t} scope={scope} setScope={setScope}
        onLaunch={startBuild} onStop={stopBuild}
        running={!!buildStatus?.running} busy={starting || sources.size === 0}
        hint={scope === "test" ? t("launchScienceTestHint") : t("launchScienceFullHint")}
        launchLabel={launchLabel}
        launchTestId="audit-science-scan-btn"
      >
        <div>
          <span className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
            {t("auditScienceSources")}
          </span>
          <div className="grid grid-cols-2 gap-1.5">
            {SOURCE_DEFS.map((s) => (
              <label
                key={s.id}
                data-testid={`science-source-${s.id}`}
                className={`flex items-center gap-2 px-2 py-1.5 border rounded-sm cursor-pointer text-[10px] font-mono ${
                  sources.has(s.id)
                    ? "border-accent/50 bg-accent/10 text-slate-200"
                    : "border-line text-slate-500 hover:bg-raised"
                }`}
              >
                <input
                  type="checkbox"
                  checked={sources.has(s.id)}
                  onChange={() => toggleSource(s.id)}
                  disabled={buildStatus?.running}
                  className="accent-[#a78bfa]"
                />
                <span className="truncate">{t(s.labelKey)}</span>
              </label>
            ))}
          </div>
        </div>
      </LaunchScope>
      {buildStatus?.run_id && (
        <p className="font-mono text-[10px] text-accent/80" data-testid="science-run-id">
          {t("currentRun")} {buildStatus.run_id}
        </p>
      )}
      {buildStatus?.running && (
        <p className="font-mono text-[10px] text-slate-400 flex items-center gap-1">
          <Loader2 size={11} className="animate-spin" /> {buildStatus.progress}/{buildStatus.total}
        </p>
      )}
      {summary && !buildStatus?.running && (
        <div className="text-[9px] font-mono text-slate-500" data-testid="audit-science-summary">
          <p>✓ +{summary.inserted ?? 0} · ~{summary.updated ?? 0} · {summary.unlocated ?? 0} {t("journalUnlocated")}</p>
          {SOURCE_DEFS.filter((s) => perSource[s.id]).map((s) => {
            const st = perSource[s.id];
            return (
              <p key={s.id} className="truncate">
                {t(s.labelKey)} : {st.fetched ?? 0} · +{st.inserted ?? 0} · ~{st.updated ?? 0}
              </p>
            );
          })}
        </div>
      )}
    </div>
  );
}
