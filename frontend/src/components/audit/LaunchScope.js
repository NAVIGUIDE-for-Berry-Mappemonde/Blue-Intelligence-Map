import { Play, Square } from "lucide-react";

/**
 * Chrome commun Test | Full | Lancer (+ Stop) pour toutes les cartes Console.
 */
export default function LaunchScope({
  t, scope, setScope, onLaunch, onStop, running, busy, hint, launchLabel, launchTestId, children,
}) {
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <button
          type="button"
          data-testid="mode-test-btn"
          onClick={() => setScope("test")}
          className={`flex-1 py-1.5 text-xs font-semibold border rounded-sm ${scope === "test" ? "border-sonar/50 bg-sonar/10 text-sonar" : "border-line text-slate-400 hover:bg-raised"}`}
        >
          {t("modeTest")}
        </button>
        <button
          type="button"
          data-testid="mode-full-btn"
          onClick={() => setScope("full")}
          className={`flex-1 py-1.5 text-xs font-semibold border rounded-sm ${scope === "full" ? "border-sonar/50 bg-sonar/10 text-sonar" : "border-line text-slate-400 hover:bg-raised"}`}
        >
          {t("modeFull")}
        </button>
      </div>
      {hint && (
        <p className="font-mono text-[9px] text-slate-500 leading-relaxed">{hint}</p>
      )}
      {children}
      <div className="flex gap-2">
        <button
          type="button"
          data-testid={launchTestId}
          onClick={onLaunch}
          disabled={busy || running}
          className="flex-1 flex items-center justify-center gap-2 py-2 font-heading font-bold text-sm rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Play size={14} /> {launchLabel || t("launchRun")}
        </button>
        {onStop && (
          <button
            type="button"
            data-testid={`${launchTestId}-stop`}
            onClick={onStop}
            disabled={!running}
            className="flex items-center justify-center gap-1.5 px-3 py-2 font-semibold text-xs rounded-sm border border-alert/50 text-alert hover:bg-alert/10 disabled:opacity-30"
          >
            <Square size={12} /> {t("stopSwarm")}
          </button>
        )}
      </div>
    </div>
  );
}
