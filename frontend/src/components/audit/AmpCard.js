import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import api from "../../api";
import { invalidateRuns } from "../../lib/runCache";
import LaunchScope from "./LaunchScope";

export default function AmpCard({ t, rulesPayload }) {
  const [scope, setScope] = useState("test");
  const [stats, setStats] = useState(null);
  const [job, setJob] = useState(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef(null);
  const extra = () => (rulesPayload ? rulesPayload() : {});

  const load = async () => {
    try {
      const { data } = await api.get("/amp/stats");
      setStats(data);
    } catch (_) { /* transient */ }
  };

  useEffect(() => {
    load();
    const i = setInterval(load, 8000);
    return () => clearInterval(i);
  }, []);

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/amp/discover-visit-urls/status");
        if (alive) setJob(data);
        if (data && !data.running) load();
      } catch (_) { /* transient */ }
    };
    check();
    pollRef.current = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRef.current); };
  }, []);

  const startDiscover = async () => {
    if (starting || job?.running) return;
    setStarting(true);
    try {
      await api.post("/amp/discover-visit-urls", {
        limit: scope === "test" ? 25 : 0,
        skip_search: false,
        from_scratch: scope === "full",
        harvest_polygons: scope === "full",
        scope,
        ...extra(),
      });
      invalidateRuns("amp");
    } catch (e) {
      setJob({ error: e.response?.data?.detail || e.message });
    } finally {
      setTimeout(() => setStarting(false), 800);
    }
  };

  const stopDiscover = async () => {
    try { await api.post("/amp/discover-visit-urls/cancel"); }
    catch (_) { /* already stopped */ }
  };

  const running = Boolean(job?.running);
  const summary = job?.summary;

  return (
    <div className="space-y-3" data-testid="amp-launch">
      <LaunchScope
        t={t} scope={scope} setScope={setScope}
        onLaunch={startDiscover} onStop={stopDiscover}
        running={running} busy={starting}
        hint={scope === "test" ? t("launchAmpTestHint") : t("launchAmpFullHint")}
        launchLabel={t("launchRun")}
        launchTestId="amp-resolve-visit-btn"
      />
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px] text-slate-300" data-testid="amp-audit-stats">
        <dt className="text-slate-500">{t("ampCached")}</dt>
        <dd className="font-mono">{stats?.total ?? "—"}</dd>
        <dt className="text-slate-500">{t("ampVisitUrl")}</dt>
        <dd className="font-mono text-[#4ade80]">{stats?.with_visit_url ?? "—"}</dd>
      </dl>
      {job?.run_id && (
        <p className="font-mono text-[10px] text-[#4ade80]/80" data-testid="amp-run-id">
          {t("currentRun")} {job.run_id}
        </p>
      )}
      {running && (
        <p className="font-mono text-[10px] text-slate-400 flex items-center gap-1">
          <Loader2 size={11} className="animate-spin" /> {job.progress}/{job.total}
        </p>
      )}
      {summary && !running && (
        <p className="font-mono text-[10px] text-slate-500" data-testid="amp-resolve-summary">
          {t("ampDiscoverSummary")
            .replace("{found}", String(summary.found ?? 0))
            .replace("{links}", String(summary.from_links ?? 0))
            .replace("{fetch}", String(summary.from_fetch ?? 0))
            .replace("{search}", String(summary.from_search ?? 0))
            .replace("{rejected}", String(summary.rejected_same_as_manager ?? 0))}
        </p>
      )}
      {job?.error && <p className="text-[11px] text-alert">{job.error}</p>}
    </div>
  );
}
