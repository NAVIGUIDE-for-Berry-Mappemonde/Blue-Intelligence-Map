import { ExternalLink, Fish, FileText, Bot } from "lucide-react";

const STATUS_COLORS = {
  PENDING: "text-amberx border-amberx/40",
  RUNNING: "text-sonar border-sonar/40",
  SUCCESS: "text-bio border-bio/40",
  MERGED: "text-bio border-bio/40",
  FAILED: "text-alert border-alert/40",
  REJECTED: "text-alert border-alert/40",
  CANCELLED: "text-slate-500 border-line",
};

export default function AgentConsole({ t, agents }) {
  return (
    <section className="p-4 border-b border-line" data-testid="agent-console">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">{t("liveConsole")}</p>
      {agents.length === 0 && (
        <p className="text-xs text-slate-500 font-mono">{t("noAgents")}</p>
      )}
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {agents.map((a) => (
          <div key={a.id} data-testid={`agent-card-${a.id}`}
            className="console-scanlines bg-black/50 border border-line rounded-sm p-2.5">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                {a.engine.includes("TinyFish") ? (
                  <a href="https://tinyfish.ai" target="_blank" rel="noreferrer"
                    className="flex items-center gap-1 text-sonar hover:underline font-mono text-[11px] font-bold">
                    <Fish size={12} /> {a.engine}
                  </a>
                ) : a.engine.includes("Readability") ? (
                  <span className="flex items-center gap-1 text-bio font-mono text-[11px] font-bold">
                    <FileText size={12} /> {a.engine}
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-amberx font-mono text-[11px] font-bold">
                    <Bot size={12} /> {a.engine}
                  </span>
                )}
                <span className="font-mono text-[10px] text-slate-500">#{a.id}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[9px] uppercase text-funder">{a.mode}</span>
                <span className={`font-mono text-[9px] px-1.5 py-0.5 border rounded-sm ${STATUS_COLORS[a.status] || "text-slate-400 border-line"}`}>
                  {a.status}
                </span>
              </div>
            </div>
            <p className="font-mono text-[10px] text-slate-400 truncate" title={a.url}>{a.url}</p>
            {a.live_url && (
              <a href={a.live_url} target="_blank" rel="noreferrer" data-testid={`agent-live-link-${a.id}`}
                className="inline-flex items-center gap-1 font-mono text-[10px] text-sonar hover:underline mt-1">
                <ExternalLink size={10} /> {t("viewAgent")}
              </a>
            )}
            {a.logs?.length > 0 && (
              <div className="mt-1.5 border-t border-line/50 pt-1 space-y-0.5">
                {a.logs.slice(-3).map((l, i) => (
                  <p key={i} className="font-mono text-[9px] text-slate-500 truncate">{l}</p>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
