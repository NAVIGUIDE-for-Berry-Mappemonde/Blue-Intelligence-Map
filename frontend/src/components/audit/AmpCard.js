import { useEffect, useRef, useState } from "react";
import { Loader2, Shield, Square } from "lucide-react";
import api from "../../api";
import CardShell from "./CardShell";

export default function AmpCard({ t }) {
  const [stats, setStats] = useState(null);
  const [job, setJob] = useState(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef(null);

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
      await api.post("/amp/discover-visit-urls", { limit: 200, skip_search: false });
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
    <div data-testid="audit-batch-hub" data-mode-card="amp">
      <CardShell title={t("modeAmp")} icon={<Shield size={13} className="text-[#4ade80]" />} borderCls="border-[#4ade80]/40">
        <p className="text-[11px] text-slate-400 leading-relaxed">{t("ampAuditHint")}</p>
        <p className="text-[11px] text-slate-500 leading-relaxed">{t("ampDiscoverHint")}</p>
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px] text-slate-300" data-testid="amp-audit-stats">
          <dt className="text-slate-500">{t("ampCached")}</dt>
          <dd className="font-mono">{stats?.total ?? "—"}</dd>
          <dt className="text-slate-500">{t("ampManagerUrl")}</dt>
          <dd className="font-mono">{stats?.with_manager_url ?? "—"}</dd>
          <dt className="text-slate-500">{t("ampVisitUrl")}</dt>
          <dd className="font-mono text-[#4ade80]">{stats?.with_visit_url ?? "—"}</dd>
          <dt className="text-slate-500">{t("ampVisitCoverage")}</dt>
          <dd className="font-mono">{stats?.visit_coverage != null ? `${stats.visit_coverage} %` : "—"}</dd>
        </dl>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="amp-resolve-visit-btn"
            onClick={startDiscover}
            disabled={starting || running}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 border border-[#4ade80]/50 bg-[#4ade80]/10 hover:bg-[#4ade80]/20 disabled:opacity-70 text-[#4ade80] font-semibold text-xs rounded-sm"
          >
            {running
              ? <><Loader2 size={13} className="animate-spin" /> {job.progress}/{job.total}</>
              : starting
                ? <><Loader2 size={13} className="animate-spin" /> {t("ampResolving")}</>
                : t("ampResolveVisit")}
          </button>
          {running && (
            <button
              type="button"
              data-testid="amp-discover-stop-btn"
              onClick={stopDiscover}
              className="px-3 py-2 border border-line text-slate-300 hover:bg-raised rounded-sm"
              title={t("ampDiscoverStop")}
            >
              <Square size={13} />
            </button>
          )}
        </div>
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
        {job?.error && (
          <p className="text-[11px] text-alert">{job.error}</p>
        )}
        {summary?.no_tinyfish_key && !running && (
          <p className="font-mono text-[10px] text-slate-500">{t("ampDiscoverNoKey")}</p>
        )}
      </CardShell>
    </div>
  );
}
