import { Anchor, ClipboardCheck, Compass, FlaskConical, Map as MapIcon, Moon, Radar, Radio, ScrollText, Settings, Shield, Ship, Sun, UserPlus, Waves, Wind } from "lucide-react";
import RunSelector from "./RunSelector";
import { HELLOASSO_MEMBERSHIP_URL } from "../config/helloasso";
import { nextBasemap } from "./map/basemaps";

// Icône et libellé du PROCHAIN fond de carte (le bouton annonce sa destination).
const BASEMAP_NEXT_UI = {
  dark: { Icon: Moon, titleKey: "darkMap" },
  light: { Icon: Sun, titleKey: "lightMap" },
  sea: { Icon: Ship, titleKey: "seaMap" },
};

export default function Header({
  lang, setLang, view, setView, showSettings, setShowSettings,
  status, t, basemap, setBasemap,
  mode, setMode,
  mapRun, onSelectMapRun,
  isAdmin = false,
}) {
  return (
    <header className="h-14 shrink-0 flex items-center justify-between px-5 border-b border-line bg-surface z-[1200]">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 flex items-center justify-center border border-accent/40 bg-accent/10 rounded-sm">
          <Waves size={18} className="text-accent" />
        </div>
        <div>
          <h1 className="font-heading font-black text-lg leading-none tracking-tight text-white">
            Blue Intelligence
          </h1>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent/70 leading-none mt-1">
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
        {/* Seven-mode switch — projects / marinas / capitaineries / formalities / amp / science / climatology */}
        <div
          className="flex border border-line rounded-sm overflow-hidden"
          title={t("modeSwitchTitle")}
          data-testid="mode-switch"
        >
          <button
            data-testid="mode-toggle-projects"
            onClick={() => setMode("projects")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition-colors border-r border-line ${
              mode === "projects"
                ? "bg-sonar/15 text-sonar"
                : "text-slate-400 hover:text-slate-200 hover:bg-raised"
            }`}
          >
            <Compass size={13} /> <span className="hidden xl:inline">{t("modeProjects")}</span>
          </button>
          <button
            data-testid="mode-toggle-marinas"
            onClick={() => setMode("marinas")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition-colors border-r border-line ${
              mode === "marinas"
                ? "bg-alert/15 text-alert"
                : "text-slate-400 hover:text-slate-200 hover:bg-raised"
            }`}
          >
            <Anchor size={13} /> <span className="hidden xl:inline">{t("modeMarinas")}</span>
          </button>
          <button
            data-testid="mode-toggle-capitaineries"
            onClick={() => setMode("capitaineries")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition-colors border-r border-line ${
              mode === "capitaineries"
                ? "bg-accent/15 text-accent"
                : "text-slate-400 hover:text-slate-200 hover:bg-raised"
            }`}
          >
            <Radio size={13} /> <span className="hidden xl:inline">{t("modeCapitaineries")}</span>
          </button>
          <button
            data-testid="mode-toggle-formalities"
            onClick={() => setMode("formalities")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition-colors border-r border-line ${
              mode === "formalities"
                ? "bg-amberx/15 text-amberx"
                : "text-slate-400 hover:text-slate-200 hover:bg-raised"
            }`}
          >
            <ScrollText size={13} /> <span className="hidden xl:inline">{t("modeFormalities")}</span>
          </button>
          <button
            data-testid="mode-toggle-amp"
            onClick={() => setMode("amp")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition-colors border-r border-line ${
              mode === "amp"
                ? "bg-[#4ade80]/15 text-[#4ade80]"
                : "text-slate-400 hover:text-slate-200 hover:bg-raised"
            }`}
          >
            <Shield size={13} /> <span className="hidden xl:inline">{t("modeAmp")}</span>
          </button>
          <button
            data-testid="mode-toggle-science"
            onClick={() => setMode("science")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition-colors border-r border-line ${
              mode === "science"
                ? "bg-[#a78bfa]/15 text-[#a78bfa]"
                : "text-slate-400 hover:text-slate-200 hover:bg-raised"
            }`}
          >
            <FlaskConical size={13} /> <span className="hidden xl:inline">{t("modeScience")}</span>
          </button>
          <button
            data-testid="mode-toggle-climatology"
            onClick={() => setMode("climatology")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition-colors ${
              mode === "climatology"
                ? "bg-[#fb923c]/15 text-[#fb923c]"
                : "text-slate-400 hover:text-slate-200 hover:bg-raised"
            }`}
          >
            <Wind size={13} /> <span className="hidden xl:inline">{t("modeClimatology")}</span>
          </button>
        </div>
        <div className="flex border border-line rounded-sm overflow-hidden">
          <button
            data-testid="view-toggle-map"
            onClick={() => setView("map")}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold ${view === "map" ? "bg-accent/15 text-accent" : "text-slate-400 hover:text-slate-200 hover:bg-raised"}`}
          >
            <MapIcon size={13} /> {t("map")}
          </button>
          {/* "Runs ›" — sélecteur du run affiché sur la carte (par mode).
              Masqué en Science et Climatologie : snapshot / moisson live,
              pas de geojson par run. */}
          {mode !== "science" && mode !== "climatology" && (
            <RunSelector
              mode={mode}
              mapRun={mapRun}
              t={t}
              onSelect={(run) => { onSelectMapRun(run); setView("map"); }}
            />
          )}
          {/* Console et Review : réservés à l'admin (?admin=<clé>) */}
          {isAdmin && (
            <button
              data-testid="view-toggle-audit"
              onClick={() => setView("audit")}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border-l border-line ${view === "audit" ? "bg-accent/15 text-accent" : "text-slate-400 hover:text-slate-200 hover:bg-raised"}`}
            >
              <Radar size={13} /> {t("audit")}
            </button>
          )}
          {isAdmin && mode !== "science" && mode !== "climatology" && (
            <button
              data-testid="view-toggle-review"
              onClick={() => setView("review")}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border-l border-line ${view === "review" ? "bg-accent/15 text-accent" : "text-slate-400 hover:text-slate-200 hover:bg-raised"}`}
            >
              <ClipboardCheck size={13} /> {t("review")}
            </button>
          )}
        </div>
        <a
          href={HELLOASSO_MEMBERSHIP_URL}
          target="_blank"
          rel="noopener noreferrer"
          data-testid="membership-cta"
          title={t("membershipCtaTooltip")}
          className="flex items-center gap-2 px-3 py-1.5 border border-bio/40 bg-bio/10 hover:bg-bio/15 rounded-sm text-bio font-semibold text-xs transition-colors"
        >
          <UserPlus size={13} />
          <span className="hidden md:inline">{t("membershipCta")}</span>
        </a>
        <div className="flex border border-line rounded-sm overflow-hidden font-mono text-xs">
          <button
            data-testid="lang-toggle-en"
            onClick={() => setLang("en")}
            className={`px-2.5 py-1.5 ${lang === "en" ? "bg-accent/15 text-accent" : "text-slate-400 hover:bg-raised"}`}
          >EN</button>
          <button
            data-testid="lang-toggle-fr"
            onClick={() => setLang("fr")}
            className={`px-2.5 py-1.5 border-l border-line ${lang === "fr" ? "bg-accent/15 text-accent" : "text-slate-400 hover:bg-raised"}`}
          >FR</button>
        </div>
        {(() => {
          const next = nextBasemap(basemap);
          const { Icon, titleKey } = BASEMAP_NEXT_UI[next] || BASEMAP_NEXT_UI.dark;
          return (
            <button
              data-testid="basemap-toggle-btn"
              onClick={() => setBasemap(next)}
              className="p-2 border border-line rounded-sm text-slate-400 hover:text-slate-200 hover:bg-raised"
              title={t(titleKey)}
            >
              <Icon size={15} />
            </button>
          );
        })()}
        <button
          data-testid="settings-toggle-btn"
          onClick={() => setShowSettings(!showSettings)}
          className={`p-2 border border-line rounded-sm ${showSettings ? "bg-accent/15 text-accent" : "text-slate-400 hover:text-slate-200 hover:bg-raised"}`}
          title={t("settings")}
        >
          <Settings size={15} />
        </button>
      </div>
    </header>
  );
}
