import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import api from "../../api";
import LaunchScope from "./LaunchScope";

const FRANCE_MRGID = 5677;

export default function FormalitiesCard({ t, onPoeRefresh, rulesPayload }) {
  const [scope, setScope] = useState("test");
  const [autoStatus, setAutoStatus] = useState(null);
  const [poeStarting, setPoeStarting] = useState(false);
  const [poeRuns, setPoeRuns] = useState([]);
  const [activeIds, setActiveIds] = useState([]);
  const pollRefs = useRef({});
  const extra = () => (rulesPayload ? rulesPayload() : {});

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const [auto, runs] = await Promise.all([
          api.get("/poe/auto-refresh/status"),
          api.get("/poe/runs"),
        ]);
        if (!alive) return;
        setAutoStatus(auto.data);
        setPoeRuns(runs.data.items || []);
        setActiveIds(runs.data.active_run_ids || []);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.all = setInterval(check, 4000);
    return () => { alive = false; clearInterval(pollRefs.current.all); };
  }, []);

  const poeRunning = activeIds.length > 0;

  const launch = async () => {
    if (poeStarting || poeRunning) return;
    setPoeStarting(true);
    try {
      if (scope === "test") {
        await api.post("/poe/runs", { variant: "tinyfish", zones: [FRANCE_MRGID], ...extra() });
      } else {
        await api.post("/poe/runs", { variant: "tinyfish", ...extra() });
      }
      if (onPoeRefresh) onPoeRefresh();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setTimeout(() => setPoeStarting(false), 800); }
  };

  const stop = async () => {
    const rid = activeIds[0];
    if (!rid) return;
    try { await api.post(`/poe/runs/${rid}/cancel`); }
    catch (e) { alert(e.response?.data?.detail || e.message); }
  };

  return (
    <div className="space-y-3" data-testid="formalities-launch">
      <LaunchScope
        t={t} scope={scope} setScope={setScope}
        onLaunch={launch} onStop={stop}
        running={poeRunning} busy={poeStarting}
        hint={scope === "test" ? t("launchPoeTestHint") : t("launchPoeFullHint")}
        launchLabel={t("launchRun")}
        launchTestId="poe-run-start-btn"
      />
      {(activeIds[0] || poeRuns[0]) && (
        <p className="font-mono text-[10px] text-amberx/80" data-testid="poe-run-id">
          {t("currentRun")} {activeIds[0] || poeRuns[0]?.id}
        </p>
      )}
      {poeRunning && (
        <p className="font-mono text-[10px] text-slate-400 flex items-center gap-1">
          <Loader2 size={11} className="animate-spin" /> {t("runningStatus")}
        </p>
      )}
      <div data-testid="poe-auto-refresh-section">
        <p className="font-mono text-[9px] uppercase tracking-widest text-slate-400">
          ♻ {t("poeAutoRefreshTitle")} · {autoStatus?.cycle_running ? t("poeAutoCycleRunning") : t("poeAutoActive")}
        </p>
      </div>
    </div>
  );
}
