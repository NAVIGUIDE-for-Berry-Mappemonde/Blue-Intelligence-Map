import { Compass, Flag, Search } from "lucide-react";
import ProjectList from "./ProjectList";

/**
 * Bandeau latéral du mode Projets — structure uniforme des 3 modes :
 * en-tête (icône + titre + compteur) → recherche → filtres → liste → action.
 * La légende cliquable fait office de filtre par catégorie (le menu déroulant
 * redondant a été retiré).
 */
export default function SwarmPanel({ t, projects, funders, funderFilter, setFunderFilter, searchQuery, setSearchQuery, categories, categoryFilter, setCategoryFilter, onReport }) {
  const legendCats = (categories || []).filter((c) => c.count > 0);

  return (
    <aside className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface min-h-0" data-testid="swarm-panel">
      <div className="flex-1 overflow-y-auto min-h-0">
        {/* En-tête + recherche */}
        <section className="p-4 border-b border-line" data-testid="projects-panel-header">
          <div className="flex items-center gap-2 mb-3">
            <Compass size={18} className="text-sonar" />
            <h2 className="font-heading font-bold text-white text-base">{t("modeProjects")}</h2>
            <span className="ml-auto font-mono text-[10px] text-slate-500" data-testid="projects-count">
              {funders.total} {t("projects")}
            </span>
          </div>
          <div className="relative">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              data-testid="project-search-input"
              type="text"
              name="project-search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t("searchPlaceholder")}
              className="w-full bg-raised border border-line rounded-sm pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
          </div>
        </section>

        {/* Filtre par organisation */}
        <section className="p-4 border-b border-line">
          <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1" htmlFor="org-filter-select">
            {t("orgFilter")}
          </label>
          <select
            id="org-filter-select"
            data-testid="org-filter-select"
            value={funderFilter}
            onChange={(e) => setFunderFilter(e.target.value)}
            className="w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent/50"
          >
            <option value="All">{t("allOrgs")} ({funders.total} {t("projects")})</option>
            {funders.funders.map((f) => (
              <option key={f.name} value={f.name}>{f.name} ({f.count})</option>
            ))}
          </select>
        </section>

        {/* Légende cliquable = filtre par catégorie */}
        <section className="p-4 border-b border-line" data-testid="map-legend">
          <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-2">{t("legend")}</p>
          <div className="grid grid-cols-1 gap-0.5">
            {legendCats.map((c) => (
              <button key={c.name} data-testid={`legend-item-${c.name}`}
                onClick={() => setCategoryFilter(categoryFilter === c.name ? "All" : c.name)}
                className={`flex items-center gap-2 py-1 px-1.5 rounded-sm text-left ${categoryFilter === c.name ? "bg-raised ring-1 ring-accent/40" : "hover:bg-raised/60"}`}>
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: c.color, boxShadow: `0 0 6px ${c.color}66` }} />
                <span className="text-[11px] text-slate-300 truncate">{t("cat_" + c.name)}</span>
                <span className="font-mono text-[9px] text-slate-500 ml-auto">{c.count}</span>
              </button>
            ))}
          </div>
        </section>

        <ProjectList t={t} projects={projects} funderFilter={funderFilter} searchQuery={searchQuery} categoryFilter={categoryFilter} />
      </div>

      {/* Action de pied — signaler un projet manquant */}
      <div className="shrink-0 p-3 border-t border-line bg-surface">
        <button
          data-testid="report-project-btn"
          onClick={onReport}
          className="w-full flex items-center justify-center gap-1.5 py-2 text-xs font-semibold border border-amberx/40 text-amberx rounded-sm hover:bg-amberx/10"
        >
          <Flag size={12} /> {t("reportBtn")}
        </button>
      </div>
    </aside>
  );
}
