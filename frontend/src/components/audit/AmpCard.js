import { useEffect, useState } from "react";
import { Loader2, Shield } from "lucide-react";
import api from "../../api";
import CardShell from "./CardShell";

export default function AmpCard({ t }) {
  const [stats, setStats] = useState(null);
  const [resolving, setResolving] = useState(false);
  const [resolveOut, setResolveOut] = useState(null);

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

  const resolveVisit = async () => {
    if (resolving) return;
    setResolving(true);
    try {
      const { data } = await api.post("/amp/resolve-visit-urls", null, { params: { limit: 800 } });
      setResolveOut(data);
      await load();
    } catch (e) {
      setResolveOut({ error: e.response?.data?.detail || e.message });
    } finally {
      setResolving(false);
    }
  };

  return (
    <div data-testid="audit-batch-hub" data-mode-card="amp">
      <CardShell title={t("modeAmp")} icon={<Shield size={13} className="text-[#4ade80]" />} borderCls="border-[#4ade80]/40">
        <p className="text-[11px] text-slate-400 leading-relaxed">{t("ampAuditHint")}</p>
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
        <button
          type="button"
          data-testid="amp-resolve-visit-btn"
          onClick={resolveVisit}
          disabled={resolving}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-[#4ade80]/50 bg-[#4ade80]/10 hover:bg-[#4ade80]/20 disabled:opacity-70 text-[#4ade80] font-semibold text-xs rounded-sm"
        >
          {resolving
            ? <><Loader2 size={13} className="animate-spin" /> {t("ampResolving")}</>
            : t("ampResolveVisit")}
        </button>
        {resolveOut && !resolveOut.error && (
          <p className="font-mono text-[10px] text-slate-500" data-testid="amp-resolve-summary">
            {t("ampResolveSummary")
              .replace("{found}", String(resolveOut.found ?? 0))
              .replace("{rejected}", String(resolveOut.rejected_same_as_manager ?? 0))}
          </p>
        )}
        {resolveOut?.error && (
          <p className="text-[11px] text-alert">{resolveOut.error}</p>
        )}
      </CardShell>
    </div>
  );
}
