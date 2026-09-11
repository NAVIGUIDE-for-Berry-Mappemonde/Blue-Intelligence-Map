import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import api from "../../api";
import LaunchScope from "./LaunchScope";

export default function CapitaineriesCard({ t, rulesPayload }) {
  const [scope, setScope] = useState("test");
  const [buildStatus, setBuildStatus] = useState(null);
  const [batchStatus, setBatchStatus] = useState(null);
  const [starting, setStarting] = useState(false);
  const pollRefs = useRef({});
  const extra = () => (rulesPayload ? rulesPayload() : {});

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const [b, e] = await Promise.all([
          api.get("/capitaineries/build/status"),
          api.get("/capitaineries/enrich-batch/status"),
        ]);
        if (!alive) return;
        setBuildStatus(b.data);
        setBatchStatus(e.data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.all = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.all); };
  }, []);

  const running = !!(buildStatus?.running || batchStatus?.running);

  const launch = async () => {
    if (starting || running) return;
    setStarting(true);
    try {
      await api.post("/capitaineries/build", {
        resume: scope === "full",
        clear_before: false,
        scope,
        ...extra(),
      });
    } catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setTimeout(() => setStarting(false), 800); }
  };

  const stop = async () => {
    try {
      if (buildStatus?.running) await api.post("/capitaineries/build/cancel");
      if (batchStatus?.running) await api.post("/capitaineries/enrich-batch/cancel");
    } catch (e) { console.warn("capitaineries stop failed", e); }
  };

  const shom = buildStatus?.summary?.shom || {};
  const noaa = buildStatus?.summary?.noaa || {};

  return (
    <div className="space-y-3" data-testid="capitaineries-launch">
      <LaunchScope
        t={t} scope={scope} setScope={setScope}
        onLaunch={launch} onStop={stop}
        running={running} busy={starting}
        hint={scope === "test" ? t("launchOfficesTestHint") : t("launchOfficesFullHint")}
        launchLabel={t("launchRun")}
        launchTestId="audit-capitaineries-scan-btn"
      />
      {(buildStatus?.run_id || batchStatus?.run_id) && (
        <p className="font-mono text-[10px] text-accent/80" data-testid="capitainerie-run-id">
          {t("currentRun")} {buildStatus?.run_id || batchStatus?.run_id}
        </p>
      )}
      {buildStatus?.running && (
        <p className="font-mono text-[10px] text-slate-400 flex items-center gap-1">
          <Loader2 size={11} className="animate-spin" /> {buildStatus.progress}/{buildStatus.total}
        </p>
      )}
      {buildStatus?.summary && !buildStatus.running && (
        <p className="text-[9px] font-mono text-slate-500" data-testid="audit-capitaineries-summary">
          ✓ OSM +{buildStatus.summary.inserted ?? 0} · ~{buildStatus.summary.updated ?? 0}
          {" · "}SHOM +{shom.inserted ?? 0} · NOAA +{noaa.inserted ?? 0}
        </p>
      )}
      {buildStatus?.error && !buildStatus.running && (
        <p className="text-[9px] font-mono text-alert">✗ {String(buildStatus.error).slice(0, 90)}</p>
      )}
    </div>
  );
}
