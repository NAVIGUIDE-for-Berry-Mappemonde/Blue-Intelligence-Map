import { useCallback, useEffect, useState } from "react";
import api from "../../api";
import { differsFromCdc, loc, RUNS_API, sourceLabel, valuesFromChosen } from "../../lib/runRules";
import { JournalDownloadButton } from "./RunJournal";

function hash8(h) {
  return (h || "").slice(0, 8) || "—";
}

export default function RunsPanel({ t, lang, mode, catalog, onReuse }) {
  const [items, setItems] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [sameOpen, setSameOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const spec = RUNS_API[mode] || RUNS_API.projects;

  const load = useCallback(async () => {
    try {
      const { data } = await api.get(spec.list);
      return data.items || [];
    } catch (_) {
      return null;
    }
  }, [spec.list]);

  useEffect(() => {
    let alive = true;
    setItems([]);
    setReady(false);
    (async () => {
      const rows = await load();
      if (!alive) return;
      if (rows) setItems(rows);
      setReady(true);
    })();
    const i = setInterval(async () => {
      const rows = await load();
      if (alive && rows) setItems(rows);
    }, 8000);
    return () => { alive = false; clearInterval(i); };
  }, [load]);

  const open = async (row) => {
    const id = row.id || row._id;
    if (openId === id) { setOpenId(null); setDetail(null); return; }
    setOpenId(id);
    setSameOpen(false);
    const chosen = row.params?.rules?.chosen || row.chosen;
    if (chosen && Object.keys(chosen).length) {
      setDetail({ ...row, id, chosen, profile: row.profile, hash: row.hash });
      return;
    }
    try {
      const { data } = await api.get(spec.detail(id));
      setDetail({ ...row, ...data, id, chosen: data.chosen || data.params?.rules?.chosen || {} });
    } catch (_) {
      setDetail({ ...row, id, chosen: {} });
    }
  };

  const split = detail ? differsFromCdc(catalog, detail.chosen) : { diffs: [], same: [] };

  return (
    <div className="space-y-3" data-testid="console-runs-panel">
      <div className="overflow-x-auto max-h-[360px] overflow-y-auto border border-line">
        <table className="w-full text-left" data-testid="runs-table">
          <thead className="sticky top-0 bg-raised">
            <tr className="font-mono text-[10px] uppercase text-slate-500">
              <th className="px-3 py-2">run_id</th>
              <th className="px-3 py-2">{t("runsDate")}</th>
              <th className="px-3 py-2">{t("statusCol")}</th>
              <th className="px-3 py-2">{t("rulesProfile")}</th>
              <th className="px-3 py-2">hash</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line/50">
            {items.map((row) => {
              const id = row.id || row._id;
              return (
                <tr
                  key={id}
                  data-testid={`run-row-${id}`}
                  onClick={() => open(row)}
                  className={`cursor-pointer hover:bg-raised/50 ${openId === id ? "bg-accent/10" : ""}`}
                >
                  <td className="px-3 py-1.5 font-mono text-[10px] text-slate-300 max-w-[140px] truncate">{id}</td>
                  <td className="px-3 py-1.5 font-mono text-[10px] text-slate-400">{(row.created_at || "").slice(0, 19)}</td>
                  <td className="px-3 py-1.5 font-mono text-[10px] text-slate-300">{row.state || "—"}</td>
                  <td className="px-3 py-1.5 font-mono text-[10px] text-accent">{row.profile || row.params?.rules?.profile || "—"}</td>
                  <td className="px-3 py-1.5 font-mono text-[10px] text-slate-400">{hash8(row.hash || row.hash8 || row.params?.rules?.hash)}</td>
                </tr>
              );
            })}
            {items.length === 0 && (
              <tr><td colSpan={5} className="px-3 py-4 font-mono text-[10px] text-slate-500">{ready ? t("runsEmpty") : "…"}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {detail && (
        <div className="border border-line bg-raised/30 p-3 space-y-2" data-testid="run-rules-detail">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent/80">{t("runRulesTitle")}</p>
          {mode === "projects" && (
            <JournalDownloadButton t={t} runId={detail.id} testId="download-run-journal-runs" />
          )}
          <p className="font-mono text-[10px] text-slate-400">
            {detail.profile || "—"} · {hash8(detail.hash || detail.hash8)}
          </p>
          {split.diffs.map((row) => {
            const rule = (catalog?.rules || []).find((r) => r.id === row.id);
            return (
              <div key={row.id} className="px-2 py-1.5 bg-accent/10 border border-accent/30 rounded-sm">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[10px] text-slate-200 flex-1">{rule ? loc(rule.title, lang) : row.id}</span>
                  <span className="font-mono text-[9px] px-1.5 py-0.5 border border-line text-slate-400">
                    {sourceLabel(row.source, t)}
                  </span>
                  <span className="font-mono text-[10px] text-accent">{String(row.value)} {row.unit || ""}</span>
                </div>
              </div>
            );
          })}
          {split.same.length > 0 && (
            <div>
              <button
                type="button"
                className="font-mono text-[10px] text-slate-500 hover:text-accent"
                onClick={() => setSameOpen((o) => !o)}
              >
                {t("runRulesSameCdc").replace("{n}", String(split.same.length))} {sameOpen ? "▾" : "▸"}
              </button>
              {sameOpen && split.same.map((row) => {
                const rule = (catalog?.rules || []).find((r) => r.id === row.id);
                return (
                  <div key={row.id} className="flex items-center gap-2 px-2 py-1">
                    <span className="font-mono text-[10px] text-slate-400 flex-1">{rule ? loc(rule.title, lang) : row.id}</span>
                    <span className="font-mono text-[9px] text-slate-500">{sourceLabel(row.source, t)}</span>
                    <span className="font-mono text-[10px] text-slate-400">{String(row.value)}</span>
                  </div>
                );
              })}
            </div>
          )}
          <button
            type="button"
            data-testid="run-reuse-rules"
            onClick={() => onReuse({
              profile: detail.profile || "cdc_default",
              values: valuesFromChosen(detail.chosen),
            })}
            className="w-full py-1.5 text-xs font-semibold border border-accent/50 text-accent rounded-sm hover:bg-accent/10"
          >
            {t("runReuseRules")}
          </button>
        </div>
      )}
    </div>
  );
}
