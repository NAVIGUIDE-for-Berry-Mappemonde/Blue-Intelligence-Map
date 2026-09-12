import { ExternalLink } from "lucide-react";

// Per-project donate buttons were removed; membership happens via the HelloAsso
// CTA in the header (Berry-Mappemonde association).
export default function ProjectList({ t, projects, funderFilter, searchQuery, categoryFilter, onFlyTo }) {
  const q = (searchQuery || "").toLowerCase();
  const features = (projects.features || []).filter(
    (f) => (funderFilter === "All" || (f.properties.funder || "").includes(funderFilter)) &&
      (categoryFilter === "All" || f.properties.category_group === categoryFilter) &&
      (!q || `${f.properties.title} ${f.properties.description} ${f.properties.funder} ${f.properties.location || ""}`.toLowerCase().includes(q))
  );

  return (
    <section className="p-4" data-testid="project-list">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">
        {t("projectList")} <span className="text-accent">({features.length})</span>
      </p>
      {features.length === 0 && (
        <p className="text-xs text-slate-500">{t("noProjects")}</p>
      )}
      <div className="divide-y divide-line/60 border border-line/60 rounded-sm">
        {features.slice(0, 100).map((f) => (
          <button
            type="button"
            key={f.properties.id}
            data-testid={`project-item-${f.properties.id}`}
            onClick={() => {
              const [lon, lat] = f.geometry?.coordinates || [];
              if (onFlyTo && lat != null && lon != null) onFlyTo(f.properties.id, lat, lon);
            }}
            className="w-full text-left p-2.5 hover:bg-raised/60"
          >
            <p className="text-xs font-semibold text-slate-200 leading-snug">{f.properties.title}</p>
            <div className="flex items-center justify-between mt-1">
              <span className="font-mono text-[10px] text-funder truncate max-w-[220px]">{f.properties.funder}</span>
              <a href={f.properties.url} target="_blank" rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="text-accent hover:text-white">
                <ExternalLink size={11} />
              </a>
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}
