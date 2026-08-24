import { Compass, Flag, Search } from "lucide-react";
import ProjectList from "./ProjectList";

export default function SwarmPanel({ t, projects, funders, funderFilter, setFunderFilter, searchQuery, setSearchQuery, categories, categoryFilter, setCategoryFilter, onReport }) {
  const legendCats = (categories || []).filter((c) => c.count > 0);
  const totalVisible = (projects.features || []).length;

  return (
    <aside className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface min-h-0" data-testid="swarm-panel">
      <div className="flex-1 overflow-y-auto min-h-0">
        {/* Phase 6 — Sidebar header (Compass icon aligned with Marinas anchor + Formalities scroll) */}
        <section className="p-4 border-b border-line" data-testid="projects-panel-header">
          <div className="flex items-center gap-2">
            <Compass size={18} className="text-sonar" />
            <h2 className="font-heading font-bold text-white text-base">{t("modeProjects")}</h2>
            <span className="ml-auto font-mono text-[10px] text-sonar/80 uppercase tracking-widest">
              {totalVisible} {t("projects")}
            </span>
          </div>
        </section>

        {/* Legend (clickable) */}
        <section className="p-4 border-b border-line" data-testid="map-legend">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">{t("legend")}</p>
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

        {/* Filters */}
        <section className="p-4 border-b border-line">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">{t("orgFilter")}</p>
          <select
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
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2 mt-3">{t("catFilter")}</p>
          <select
            data-testid="category-filter-select"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent/50"
          >
            <option value="All">{t("allCategories")}</option>
            {legendCats.map((c) => (
              <option key={c.name} value={c.name}>{t("cat_" + c.name)} ({c.count})</option>
            ))}
          </select>
          <div className="relative mt-2">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              data-testid="project-search-input"
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t("searchPlaceholder")}
              className="w-full bg-raised border border-line rounded-sm pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
          </div>
        </section>

        <ProjectList t={t} projects={projects} funderFilter={funderFilter} searchQuery={searchQuery} categoryFilter={categoryFilter} />
      </div>

      {/* Bottom action — Phase 6: only report button kept, export moved to Settings */}
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
