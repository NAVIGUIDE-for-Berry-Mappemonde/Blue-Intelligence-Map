import { useEffect, useRef, useState } from "react";
import { FlaskConical, Loader2, Square } from "lucide-react";
import api from "../../api";

const SOURCE_DEFS = [
  { id: "sextant", labelKey: "scienceSourceSextant" },
  { id: "odatis", labelKey: "scienceSourceOdatis" },
  { id: "edmed", labelKey: "scienceSourceEdmed" },
  { id: "argo", labelKey: "scienceSourceArgo" },
  { id: "csr", labelKey: "scienceSourceCsr" },
];

/**
 * ScienceCard — carte de lancement de la moisson des catalogues océano.
 * Sources cochables (Sextant, ODATIS, EDMED, Argo), upsert non destructif.
 */
export default function ScienceCard({ t, rulesPayload }) {
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

  const startBuild = async () => {
    if (starting || buildStatus?.running || sources.size === 0) return;
    setStarting(true);
    try {
      await api.post("/science/build", {
        sources: SOURCE_DEFS.map((s) => s.id).filter((id) => sources.has(id)),
        ...extra(),
      });
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
      <div>
        <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
          {t("auditScienceBuild")}
        </label>
        <p className="mb-2 text-[10px] font-mono text-slate-500 leading-relaxed">
          {t("auditScienceHint")}
        </p>
        {buildStatus?.run_id && (
          <p className="mb-2 font-mono text-[10px] text-accent/80" data-testid="science-run-id">
            {t("currentRun")} {buildStatus.run_id}
          </p>
        )}
        <div className="mb-2">
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
        <div className="flex gap-2">
          <button
            data-testid="audit-science-scan-btn"
            onClick={startBuild}
            disabled={starting || buildStatus?.running || sources.size === 0}
            className="flex-1 flex items-center justify-center gap-2 px-3 py-2 border border-accent/50 bg-accent/10 hover:bg-accent/20 disabled:opacity-70 disabled:cursor-not-allowed text-accent font-semibold text-xs rounded-sm"
          >
            {buildStatus?.running ? (
              <><Loader2 size={13} className="animate-spin" /> {buildStatus.progress}/{buildStatus.total}</>
            ) : (
              <><FlaskConical size={13} /> {t("scienceScan")}</>
            )}
          </button>
          {buildStatus?.running && (
            <button
              data-testid="audit-science-stop-btn"
              onClick={stopBuild}
              disabled={buildStatus?.cancelling}
              className="flex items-center justify-center gap-1.5 px-3 py-1.5 border border-accent bg-accent/25 hover:bg-accent/40 disabled:opacity-60 text-accent font-bold text-xs rounded-sm"
            >
              <Square size={11} /> {buildStatus?.cancelling ? "…" : "Stop"}
            </button>
          )}
        </div>
        {summary && !buildStatus?.running && (
          <div className="mt-1.5 text-[9px] font-mono text-slate-500 leading-relaxed" data-testid="audit-science-summary">
            <p>✓ +{summary.inserted ?? 0} · ~{summary.updated ?? 0} · {summary.unlocated ?? 0} {t("scienceCount")} sans position</p>
            {SOURCE_DEFS.filter((s) => perSource[s.id]).map((s) => {
              const st = perSource[s.id];
              return (
                <p key={s.id} className="truncate">
                  {t(s.labelKey)} : {st.fetched ?? 0} lues · +{st.inserted ?? 0} · ~{st.updated ?? 0}
                  {st.error ? ` · ✗ ${String(st.error).slice(0, 60)}` : ""}
                </p>
              );
            })}
          </div>
        )}
        {buildStatus?.error && !buildStatus.running && (
          <p className="mt-1.5 text-[9px] font-mono text-alert leading-relaxed">
            ✗ {String(buildStatus.error).slice(0, 90)}
          </p>
        )}
        {buildStatus?.running && buildStatus?.logs_tail?.length > 0 && (
          <div
            data-testid="audit-science-logs"
            className="mt-1.5 text-[9px] font-mono text-slate-500 max-h-32 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1"
          >
            {buildStatus.logs_tail.slice(-8).map((l, i) => <div key={i} className="truncate">{l}</div>)}
          </div>
        )}
      </div>
    </div>
  );
}
