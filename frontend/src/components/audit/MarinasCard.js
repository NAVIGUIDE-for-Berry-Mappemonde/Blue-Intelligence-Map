import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import api from "../../api";
import { invalidateRuns } from "../../lib/runCache";
import LaunchScope from "./LaunchScope";

export default function MarinasCard({ t, showAnchorages, setShowAnchorages, anchoragesCount, rulesPayload }) {
  const [scope, setScope] = useState("test");
  const [buildStatus, setBuildStatus] = useState(null);
  const [anchStatus, setAnchStatus] = useState(null);
  const [batchStatus, setBatchStatus] = useState(null);
  const [starting, setStarting] = useState(false);
  const pollRefs = useRef({});
  const extra = () => (rulesPayload ? rulesPayload() : {});

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const [b, a, e] = await Promise.all([
          api.get("/marinas/build/status"),
          api.get("/anchorages/build/status"),
          api.get("/marinas/enrich-batch/status"),
        ]);
        if (!alive) return;
        setBuildStatus(b.data);
        setAnchStatus(a.data);
        setBatchStatus(e.data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.all = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.all); };
  }, []);

  const running = !!(buildStatus?.running || batchStatus?.running || anchStatus?.running);

  const launch = async () => {
    if (starting || running) return;
    setStarting(true);
    try {
      await api.post("/marinas/build", {
        resume: false,
        from_scratch: scope === "full",
        maps_place_after: scope === "full",
        clear_before: false,
        scope,
        ...extra(),
      });
      invalidateRuns("marinas");
    } catch (e) { alert(e.response?.data?.detail || e.message); }
    finally { setTimeout(() => setStarting(false), 800); }
  };

  const stop = async () => {
    try {
      if (buildStatus?.running) await api.post("/marinas/build/cancel");
      if (batchStatus?.running) await api.post("/marinas/enrich-batch/cancel");
      if (anchStatus?.running) await api.post("/anchorages/build/cancel");
    } catch (e) { console.warn("marina stop failed", e); }
  };

  const hint = scope === "test" ? t("launchMarinasTestHint") : t("launchMarinasFullHint");

  return (
    <div className="space-y-3" data-testid="marinas-launch">
      <LaunchScope
        t={t} scope={scope} setScope={setScope}
        onLaunch={launch} onStop={stop}
        running={running} busy={starting}
        hint={hint}
        launchLabel={t("launchRun")}
        launchTestId="audit-marinas-scan-btn"
      />
      {(buildStatus?.run_id || batchStatus?.run_id) && (
        <p className="font-mono text-[10px] text-alert/80" data-testid="marina-run-id">
          {t("currentRun")} {buildStatus?.run_id || batchStatus?.run_id}
        </p>
      )}
      {buildStatus?.running && (
        <p className="font-mono text-[10px] text-slate-400 flex items-center gap-1">
          <Loader2 size={11} className="animate-spin" /> {buildStatus.progress}/{buildStatus.total}
        </p>
      )}
      {buildStatus?.summary && !buildStatus.running && (
        <p className="text-[9px] font-mono text-slate-500">
          ✓ +{buildStatus.summary.inserted ?? 0} · ~{buildStatus.summary.updated ?? 0} · OSM {buildStatus.summary.fetched_raw ?? 0}
        </p>
      )}
      <label
        className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none"
        data-testid="anchorages-toggle"
      >
        <input
          type="checkbox"
          checked={!!showAnchorages}
          onChange={(e) => setShowAnchorages && setShowAnchorages(e.target.checked)}
          className="accent-teal-400"
        />
        <span className="flex-1">{t("anchoragesToggle")}</span>
        <span className="font-mono text-[10px] uppercase tracking-widest text-teal-300/80" data-testid="anchorages-count">
          ⚓ {anchoragesCount ?? 0}
        </span>
      </label>
    </div>
  );
}
