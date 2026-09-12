import { useCallback, useEffect, useState } from "react";
import { Download } from "lucide-react";
import api from "../../api";

export async function downloadRunJournal(runId) {
  const { data } = await api.get(`/projects/runs/${runId}/journal`, {
    params: { format: "txt" },
    responseType: "blob",
  });
  const blob = data instanceof Blob ? data : new Blob([data], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `run-${runId}-journal.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function JournalDownloadButton({ t, runId, testId = "download-run-journal" }) {
  const [busy, setBusy] = useState(false);
  if (!runId) return null;
  const onClick = async (e) => {
    e.stopPropagation();
    setBusy(true);
    try {
      await downloadRunJournal(runId);
    } catch (err) {
      alert(err.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={busy}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 font-mono text-[10px] border border-sonar/50 text-sonar rounded-sm hover:bg-sonar/10 disabled:opacity-40"
    >
      <Download size={12} /> {busy ? "…" : t("downloadJournal")}
    </button>
  );
}

export default function RunJournalViewer({ t, runId }) {
  const [pack, setPack] = useState(null);

  const load = useCallback(async () => {
    if (!runId) return;
    try {
      const { data } = await api.get(`/projects/runs/${runId}/journal`, {
        params: { tail: true, limit: 400 },
      });
      setPack(data);
    } catch (_) { /* transient */ }
  }, [runId]);

  useEffect(() => {
    load();
    if (!runId) return undefined;
    const i = setInterval(load, 5000);
    return () => clearInterval(i);
  }, [load, runId]);

  if (!runId) {
    return <p className="font-mono text-[10px] text-slate-500">{t("journalEmpty")}</p>;
  }

  const items = pack?.items || [];
  return (
    <div className="space-y-2" data-testid="run-journal-viewer">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="font-mono text-[10px] text-slate-400">
          {t("currentRun")} {runId}
          {pack?.total != null && (
            <span className="text-slate-500"> · {t("journalLines").replace("{n}", String(pack.total))}</span>
          )}
        </p>
        <JournalDownloadButton t={t} runId={runId} />
      </div>
      <p className="font-mono text-[9px] text-slate-500 leading-relaxed">{t("journalCompleteHint")}</p>
      <div
        className="console-scanlines bg-black/60 border border-line rounded-sm h-64 overflow-y-auto p-2 font-mono text-[10px] leading-relaxed"
        data-testid="run-journal-stream"
      >
        {items.map((l, i) => (
          <div
            key={`${l.seq || i}-${l.ts || i}`}
            className={
              l.level === "error" ? "text-alert" :
              l.level === "warn" ? "text-amberx" :
              l.level === "success" ? "text-bio" :
              l.kind === "agent" ? "text-slate-400" : "text-sonar/80"
            }
          >
            <span className="text-slate-600">{(l.ts || "").slice(11, 19)}</span>
            {l.kind === "agent" && (
              <span className="text-slate-500"> [{l.agent} {l.engine || ""}]</span>
            )}
            {" "}{l.msg}
          </div>
        ))}
        {!items.length && (
          <p className="text-slate-500">{t("journalEmpty")}</p>
        )}
      </div>
    </div>
  );
}
