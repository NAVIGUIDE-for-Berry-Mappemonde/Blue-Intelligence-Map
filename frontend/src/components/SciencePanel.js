import { ExternalLink, FlaskConical, MapPin, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import api from "../api";

const LIST_CAP = 250;
const COLOR = "#a78bfa";

const SOURCE_FILTERS = [
  { id: "all", labelKey: "scienceAllSources" },
  { id: "sextant", label: "Sextant" },
  { id: "odatis", label: "ODATIS" },
  { id: "edmed", label: "EDMED" },
  { id: "argo", label: "Argo" },
  { id: "csr", label: "CSR" },
];

const WMS_LAYERS = [
  { id: "bathymetry", labelKey: "scienceWmsBathymetry" },
  { id: "substrate", labelKey: "scienceWmsSubstrate" },
  { id: "cables", labelKey: "scienceWmsCables" },
];

/**
 * SciencePanel — liste latérale du mode Science : jeux de données océano
 * (Sextant/ODATIS/EDMED) + flotteurs Argo + tracés CSR, filtres par source,
 * couches WMS EMODnet.
 */
export default function SciencePanel({ t, science, onFlyTo, onRefresh, scienceWms, onToggleWms }) {
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const features = science?.features || [];

  // Quand une moisson se termine, rafraîchir la carte + la liste.
  useEffect(() => {
    let live = true;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/science/build/status");
        if (!live) return;
        if (wasRunning && !data.running) {
          if (onRefresh) onRefresh();
        }
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    const iv = setInterval(check, 4000);
    return () => { live = false; clearInterval(iv); };
  }, [onRefresh]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return features.filter((f) => {
      const p = f.properties || {};
      if (sourceFilter !== "all" && p.source !== sourceFilter) return false;
      if (!q) return true;
      return (
        (p.name || "").toLowerCase().includes(q)
        || (p.provider || "").toLowerCase().includes(q)
        || (p.doi || "").toLowerCase().includes(q)
        || String(p.wmo || "").toLowerCase().includes(q)
        || String(p.ship || "").toLowerCase().includes(q)
      );
    });
  }, [features, query, sourceFilter]);

  const visible = filtered.slice(0, LIST_CAP);
  const truncated = filtered.length > LIST_CAP;
  const argoCount = features.filter((f) => f.properties?.kind === "argo_float").length;
  const cruiseCount = features.filter((f) => f.properties?.kind === "cruise").length;
  const datasetCount = features.length - argoCount - cruiseCount;

  return (
    <aside className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface" data-testid="science-panel">
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-2 mb-1">
          <FlaskConical size={18} className="text-accent" />
          <h2 className="font-heading font-bold text-white text-base">{t("modeScience")}</h2>
          <span className="ml-auto font-mono text-[10px] text-slate-500" data-testid="science-count">
            {features.length} {t("scienceCount")}
          </span>
        </div>
        <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-3">
          {t("scienceSubtitle")}
        </p>
        <div className="relative mb-2">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            data-testid="science-search-input"
            type="text"
            name="science-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("scienceSearch")}
            className="w-full bg-raised border border-line rounded-sm pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent/50"
          />
        </div>
        <div className="flex flex-wrap gap-1 mb-3" data-testid="science-source-filter">
          {SOURCE_FILTERS.map((s) => (
            <button
              key={s.id}
              data-testid={`science-filter-${s.id}`}
              onClick={() => setSourceFilter(s.id)}
              className={`flex-1 px-1 py-1 font-mono text-[9px] uppercase tracking-wide border rounded-sm transition-colors ${
                sourceFilter === s.id
                  ? "border-accent/60 bg-accent/15 text-accent"
                  : "border-line text-slate-500 hover:text-slate-300 hover:bg-raised"
              }`}
            >
              {s.labelKey ? t(s.labelKey) : s.label}
            </button>
          ))}
        </div>
        <div className="mb-1" data-testid="science-legend">
          <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-1.5">{t("legend")}</p>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full shrink-0" style={{ background: COLOR, boxShadow: "0 0 6px #a78bfa66" }} />
              <span className="text-[11px] text-slate-300">{t("legendScienceDataset")} · {datasetCount}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full shrink-0 border-2" style={{ borderColor: COLOR, background: "rgba(167,139,250,0.2)" }} />
              <span className="text-[11px] text-slate-300">{t("legendScienceArgo")} · {argoCount}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-6 h-0.5 shrink-0" style={{ background: COLOR }} />
              <span className="text-[11px] text-slate-300">{t("legendScienceCruise")} · {cruiseCount}</span>
            </div>
          </div>
        </div>
        <div className="mt-3" data-testid="science-wms">
          <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-1">{t("scienceWmsTitle")}</p>
          <p className="font-mono text-[9px] text-slate-500 mb-1.5 leading-relaxed">{t("scienceWmsHint")}</p>
          <div className="space-y-1">
            {WMS_LAYERS.map((layer) => (
              <label
                key={layer.id}
                data-testid={`science-wms-${layer.id}`}
                className="flex items-center gap-2 px-1 py-0.5 cursor-pointer text-[11px] text-slate-300"
              >
                <input
                  type="checkbox"
                  checked={!!(scienceWms && scienceWms[layer.id])}
                  onChange={(e) => onToggleWms && onToggleWms(layer.id, e.target.checked)}
                  className="accent-[#a78bfa]"
                />
                <span>{t(layer.labelKey)}</span>
              </label>
            ))}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto" data-testid="science-list">
        {features.length === 0 && (
          <div className="p-6 text-center text-xs text-slate-500 leading-relaxed">
            <FlaskConical size={28} className="mx-auto mb-3 text-slate-600" />
            {t("scienceEmpty")}
          </div>
        )}
        {truncated && (
          <p className="px-4 py-2 font-mono text-[10px] text-slate-500" data-testid="science-list-truncated">
            {t("marinasListTruncated").replace("{shown}", String(LIST_CAP)).replace("{total}", String(filtered.length))}
          </p>
        )}
        {visible.map((f) => {
          const p = f.properties || {};
          const isArgo = p.kind === "argo_float";
          const isCruise = p.kind === "cruise";
          const lat = p.lat != null ? Number(p.lat) : (f.geometry?.type === "Point" ? f.geometry.coordinates[1] : 0);
          const lon = p.lon != null ? Number(p.lon) : (f.geometry?.type === "Point" ? f.geometry.coordinates[0] : 0);
          const sub = isArgo
            ? [p.wmo ? `WMO ${p.wmo}` : null, p.profile_date ? String(p.profile_date).slice(0, 10) : null]
              .filter(Boolean).join(" · ")
            : isCruise
              ? [p.ship, [p.start, p.end].filter(Boolean).join(" → ")].filter(Boolean).join(" · ")
              : (p.provider || (p.date ? String(p.date).slice(0, 10) : `${Number(lat).toFixed(2)}, ${Number(lon).toFixed(2)}`));
          return (
            <button
              key={p.id}
              data-testid={`science-row-${p.id}`}
              onClick={() => onFlyTo && onFlyTo(p.id, lat, lon)}
              className="w-full text-left px-4 py-3 border-b border-line hover:bg-raised transition-colors group"
              title={t("scienceFlyTo")}
            >
              <div className="flex items-start gap-2">
                <MapPin size={13} className="text-accent mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-heading text-sm text-slate-100 truncate group-hover:text-white">
                    {p.name || t(isCruise ? "scienceUnnamedCruise" : "scienceUnnamed")}
                  </div>
                  <div className="font-mono text-[10px] text-slate-500 mt-0.5 truncate">
                    {sub}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <span className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest bg-accent/15 text-accent border-accent/40">
                      {isArgo ? t("scienceArgoFloat") : isCruise ? t("scienceCruise") : (p.source || t("scienceDataset"))}
                    </span>
                    {p.doi && (
                      <span className="px-1.5 py-0.5 border border-line rounded-sm font-mono text-[9px] text-slate-400">
                        DOI
                      </span>
                    )}
                    {p.url && (
                      <ExternalLink size={11} className="text-slate-500 ml-auto shrink-0" />
                    )}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      <div className="px-4 py-2 border-t border-line">
        <p className="font-mono text-[10px] text-slate-300 leading-relaxed">
          {t("scienceAttribution")}
        </p>
      </div>
    </aside>
  );
}
