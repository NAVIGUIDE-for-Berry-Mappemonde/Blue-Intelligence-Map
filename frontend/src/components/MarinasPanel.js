import { Anchor, ExternalLink, Loader2, MapPin, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import api from "../api";

const PRIORITY_LABELS_KEY = {
  1: "marinasPriority1",
  2: "marinasPriority2",
  3: "marinasPriority3",
};

const SOURCE_LABELS_KEY = {
  openstreetmap: "marinasSourceOSM",
  shom: "marinasSourceSHOM",
  curated: "marinasSourceCurated",
};

const PRIORITY_COLORS = {
  1: "bg-alert/20 text-alert border-alert/40",
  2: "bg-amberx/20 text-amberx border-amberx/40",
  3: "bg-slate-500/20 text-slate-300 border-slate-500/40",
};

const SOURCE_COLORS = {
  openstreetmap: "bg-bio/15 text-bio border-bio/40",
  shom:          "bg-sonar/15 text-sonar border-sonar/40",
  curated:       "bg-funder/15 text-funder border-funder/40",
};

export default function MarinasPanel({
  t,
  marinas,               // GeoJSON FeatureCollection
  onFlyTo,               // fn(featureId, lat, lon) — used to fly + open popup on the map
  onRefresh,             // fn() — parent will refetch after build
}) {
  const [query, setQuery] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("All");
  const [sourceFilter, setSourceFilter] = useState("All");
  const batchPollRef = useRef(null);

  const features = marinas?.features || [];

  // Poll build status — kept alive so the sidebar list re-fetches at end of a
  // build that was kicked off from the Audit view (Phase 5).
  useEffect(() => {
    let live = true;
    let iv = null;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/marinas/build/status");
        if (!live) return;
        if (wasRunning && !data.running) {
          if (onRefresh) onRefresh();
        }
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    iv = setInterval(check, 4000);
    return () => { live = false; if (iv) clearInterval(iv); };
  }, [onRefresh]);

  // Enrichment batch poller — same story, refresh the list at the end.
  useEffect(() => {
    let live = true;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/marinas/enrich-batch/status");
        if (!live) return;
        if (wasRunning && !data.running) {
          if (onRefresh) onRefresh();
        }
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    batchPollRef.current = setInterval(check, 3000);
    return () => {
      live = false;
      if (batchPollRef.current) clearInterval(batchPollRef.current);
    };
  }, [onRefresh]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return features.filter((f) => {
      const p = f.properties || {};
      if (priorityFilter !== "All" && String(p.priority) !== String(priorityFilter)) return false;
      if (sourceFilter !== "All" && p.source !== sourceFilter) return false;
      if (!q) return true;
      return (
        (p.name || "").toLowerCase().includes(q)
        || (p.nearest_waypoint?.name || "").toLowerCase().includes(q)
      );
    });
  }, [features, query, priorityFilter, sourceFilter]);

  const bySrc = useMemo(() => {
    const acc = { openstreetmap: 0, shom: 0, curated: 0 };
    features.forEach((f) => {
      const src = f.properties?.source;
      if (src && acc[src] !== undefined) acc[src] += 1;
    });
    return acc;
  }, [features]);

  return (
    <aside className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface" data-testid="marinas-panel">
      {/* Header block */}
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-2 mb-2">
          <Anchor size={18} className="text-alert" />
          <h2 className="font-heading font-bold text-white text-base">{t("modeMarinas")}</h2>
          <span className="ml-auto font-mono text-[10px] text-alert/80 uppercase tracking-widest">
            {features.length} {t("marinasCount")}
          </span>
        </div>

        {/* Search */}
        <div className="relative mb-3">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            data-testid="marinas-search-input"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("marinasSearch")}
            className="w-full pl-8 pr-2 py-2 bg-raised border border-line rounded-sm text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-alert/60"
          />
        </div>

        {/* Filters */}
        <div className="grid grid-cols-2 gap-2 mb-3">
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("marinasFilterPriority")}
            </label>
            <select
              data-testid="marinas-filter-priority"
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value)}
              className="w-full px-2 py-1.5 bg-raised border border-line rounded-sm text-xs text-slate-100 focus:outline-none focus:border-alert/60"
            >
              <option value="All">{t("marinasAll")}</option>
              <option value="1">1 · {t("marinasPriority1")}</option>
              <option value="2">2 · {t("marinasPriority2")}</option>
              <option value="3">3 · {t("marinasPriority3")}</option>
            </select>
          </div>
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("marinasFilterSource")}
            </label>
            <select
              data-testid="marinas-filter-source"
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="w-full px-2 py-1.5 bg-raised border border-line rounded-sm text-xs text-slate-100 focus:outline-none focus:border-alert/60"
            >
              <option value="All">{t("marinasAll")}</option>
              <option value="openstreetmap">{t("marinasSourceOSM")} ({bySrc.openstreetmap})</option>
              <option value="shom">{t("marinasSourceSHOM")} ({bySrc.shom})</option>
              <option value="curated">{t("marinasSourceCurated")} ({bySrc.curated})</option>
            </select>
          </div>
        </div>

        {/* Phase 6 — Batch controls migrated to Audit view; sidebar keeps only the list.
            Export button removed from the sidebar (available in Settings). */}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto" data-testid="marinas-list">
        {features.length === 0 && (
          <div className="p-6 text-center text-xs text-slate-500 leading-relaxed">
            <Anchor size={28} className="mx-auto mb-3 text-slate-600" />
            {t("marinasEmpty")}
          </div>
        )}
        {filtered.map((f) => {
          const p = f.properties || {};
          const wp = p.nearest_waypoint || {};
          const [lon, lat] = f.geometry?.coordinates || [0, 0];
          const prioKey = PRIORITY_LABELS_KEY[p.priority] || "marinasPriority3";
          const srcKey = SOURCE_LABELS_KEY[p.source] || "marinasSourceCurated";
          return (
            <button
              key={p.id}
              data-testid={`marina-row-${p.id}`}
              onClick={() => onFlyTo && onFlyTo(p.id, lat, lon)}
              className="w-full text-left px-4 py-3 border-b border-line hover:bg-raised transition-colors group"
              title={t("marinasFlyTo")}
            >
              <div className="flex items-start gap-2">
                <MapPin size={13} className="text-alert mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-heading text-sm text-slate-100 truncate group-hover:text-white">
                    {p.name}
                  </div>
                  <div className="font-mono text-[10px] text-slate-500 mt-0.5 truncate">
                    {t("marinasNearest")}: {wp.name || "—"} · {(wp.distance_nm ?? 0).toFixed(1)} {t("marinasDistanceNM")}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <span className={`px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest ${PRIORITY_COLORS[p.priority] || PRIORITY_COLORS[3]}`}>
                      P{p.priority} · {t(prioKey)}
                    </span>
                    <span className={`px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest ${SOURCE_COLORS[p.source] || SOURCE_COLORS.curated}`}>
                      {t(srcKey)}
                    </span>
                    {p.enriched && (
                      <span className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest bg-alert/15 text-alert border-alert/40" title={t("marinasEnriched")}>◆</span>
                    )}
                    {p.tags?.website && (
                      <ExternalLink size={11} className="text-slate-500 ml-auto shrink-0" />
                    )}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Refresh footer */}
      <div className="p-3 border-t border-line">
        <button
          onClick={() => onRefresh && onRefresh()}
          className="w-full flex items-center justify-center gap-2 px-3 py-1.5 border border-line hover:border-alert/40 hover:text-alert text-slate-400 text-xs rounded-sm"
        >
          <RefreshCw size={12} /> {t("refresh") || "Refresh"}
        </button>
      </div>
    </aside>
  );
}
