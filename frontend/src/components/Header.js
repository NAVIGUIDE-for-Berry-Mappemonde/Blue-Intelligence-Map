import { Map as MapIcon, Radar, Settings, Waves } from "lucide-react";

export default function Header({ lang, setLang, view, setView, showSettings, setShowSettings, status, t }) {
  return (
    <header className="h-14 shrink-0 flex items-center justify-between px-5 border-b border-line bg-surface z-[1200]">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 flex items-center justify-center border border-sonar/40 bg-sonar/10 rounded-sm">
          <Waves size={18} className="text-sonar" />
        </div>
        <div>
          <h1 className="font-heading font-black text-lg leading-none tracking-tight text-white">
            Blue Intelligence
          </h1>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/70 leading-none mt-1">
            {t("subtitle")}
          </p>
        </div>
        {status?.running && (
          <span className="ml-3 flex items-center gap-2 font-mono text-[10px] text-bio border border-bio/30 bg-bio/5 px-2 py-1 rounded-sm">
            <span className="w-1.5 h-1.5 rounded-full bg-bio animate-pulse" />
            SWARM {t("runningStatus")}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <div className="flex border border-line rounded-sm overflow-hidden">
          <button
            data-testid="view-toggle-map"
            onClick={() => setView("map")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold ${view === "map" ? "bg-sonar/15 text-sonar" : "text-slate-400 hover:text-slate-200 hover:bg-raised"}`}
          >
            <MapIcon size={13} /> {t("map")}
          </button>
          <button
            data-testid="view-toggle-audit"
            onClick={() => setView("audit")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border-l border-line ${view === "audit" ? "bg-sonar/15 text-sonar" : "text-slate-400 hover:text-slate-200 hover:bg-raised"}`}
          >
            <Radar size={13} /> {t("audit")}
          </button>
        </div>
        <div className="flex border border-line rounded-sm overflow-hidden font-mono text-xs">
          <button
            data-testid="lang-toggle-en"
            onClick={() => setLang("en")}
            className={`px-2.5 py-1.5 ${lang === "en" ? "bg-sonar/15 text-sonar" : "text-slate-400 hover:bg-raised"}`}
          >EN</button>
          <button
            data-testid="lang-toggle-fr"
            onClick={() => setLang("fr")}
            className={`px-2.5 py-1.5 border-l border-line ${lang === "fr" ? "bg-sonar/15 text-sonar" : "text-slate-400 hover:bg-raised"}`}
          >FR</button>
        </div>
        <button
          data-testid="settings-toggle-btn"
          onClick={() => setShowSettings(!showSettings)}
          className={`p-2 border border-line rounded-sm ${showSettings ? "bg-sonar/15 text-sonar" : "text-slate-400 hover:text-slate-200 hover:bg-raised"}`}
          title={t("settings")}
        >
          <Settings size={15} />
        </button>
      </div>
    </header>
  );
}
