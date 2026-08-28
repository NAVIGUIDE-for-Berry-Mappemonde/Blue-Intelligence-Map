import { Anchor, Clock, ScrollText, Search } from "lucide-react";
import { useMemo, useState } from "react";

// Refactor 2026-06 — Formalities mode = world map [EEZ -> Ports of Entry].
// The sidebar lists the ~285 world EEZs (VLIZ Marine Regions) with their
// generation status and PoE count. Clicking a row flies to the EEZ polygon
// and opens its popup on the map.

const STATUS_COLOR = {
  non_generee:    "bg-slate-500/15 text-slate-300 border-slate-500/40",
  ia:             "bg-amberx/15 text-amberx border-amberx/40",
  ia_sans_source: "bg-amberx/10 text-amberx border-amberx/40 border-dashed",
  erreur:         "bg-alert/10 text-alert border-alert/40",
};
const STATUS_LABEL_KEY = {
  non_generee:    "poeStatusNonGeneree",
  ia:             "poeStatusIa",
  ia_sans_source: "poeStatusIaSansSource",
  erreur:         "poeStatusErreur",
};

const flagEmoji = (iso2) => {
  if (!iso2 || iso2.length !== 2) return "🌐";
  const cc = iso2.toUpperCase();
  return String.fromCodePoint(0x1f1e6 + cc.charCodeAt(0) - 65, 0x1f1e6 + cc.charCodeAt(1) - 65);
};

export default function FormalitiesPanel({ t, zones, selectedZone, onSelectZone }) {
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("All");

  const items = zones?.items || [];
  const summary = zones?.summary || {};
  const byStatus = summary.by_status || {};
  const generatedCount = (byStatus.ia || 0) + (byStatus.ia_sans_source || 0);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return items.filter((z) => {
      if (statusFilter !== "All" && (z.status || "non_generee") !== statusFilter) return false;
      if (!needle) return true;
      return `${z.name || ""} ${z.geoname || ""} ${z.sovereign || ""}`.toLowerCase().includes(needle);
    });
  }, [items, q, statusFilter]);

  const statusBadge = (status) => {
    const s = status || "non_generee";
    return (
      <span className={`px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest ${STATUS_COLOR[s] || STATUS_COLOR.non_generee}`}>
        {t(STATUS_LABEL_KEY[s] || "poeStatusNonGeneree")}
      </span>
    );
  };

  return (
    <aside
      className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface"
      data-testid="formalities-panel"
    >
      {/* En-tête + recherche — structure uniforme des 3 modes */}
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-2 mb-3">
          <ScrollText size={18} className="text-amberx" />
          <h2 className="font-heading font-bold text-white text-base">{t("poeTitle")}</h2>
          <span className="ml-auto font-mono text-[10px] text-slate-500" data-testid="poe-zones-count">
            {items.length} {t("poeZonesCount")}
          </span>
        </div>

        <div
          data-testid="formalities-disclaimer"
          className="bi-formalities-disclaimer text-[11px] leading-relaxed px-2.5 py-2 rounded-sm mb-3"
        >
          ⚠️ {t("formalitiesDisclaimer")}
        </div>

        <div className="relative mb-3">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            data-testid="poe-search-input"
            type="text"
            name="poe-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("poeSearch")}
            className="w-full bg-raised border border-line rounded-sm pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent/50"
          />
        </div>

        {/* Filtre par statut */}
        <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1" htmlFor="poe-status-filter">
          {t("poeAllStatuses")}
        </label>
        <select
          id="poe-status-filter"
          data-testid="poe-status-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent/50"
        >
          <option value="All">{t("poeAllStatuses")}</option>
          <option value="non_generee">{t("poeStatusNonGeneree")}</option>
          <option value="ia">{t("poeStatusIa")}</option>
          <option value="ia_sans_source">{t("poeStatusIaSansSource")}</option>
          <option value="erreur">{t("poeStatusErreur")}</option>
        </select>

        {items.length > 0 && (
          <p className="mt-2 font-mono text-[9px] uppercase tracking-widest text-slate-500" data-testid="poe-summary">
            {generatedCount}/{items.length} {t("poeSummary")} · {summary.total_ports || 0} {t("poeSummaryPorts")}
          </p>
        )}
      </div>

      {/* EEZ list */}
      <div className="flex-1 overflow-y-auto" data-testid="poe-zones-list">
        {items.length === 0 && (
          <div className="p-6 text-center text-xs text-slate-500 leading-relaxed">
            <ScrollText size={28} className="mx-auto mb-3 text-slate-600" />
            {t("poeZonesEmpty")}
          </div>
        )}
        {filtered.map((z) => {
          const isSelected = selectedZone === z.mrgid;
          return (
            <button
              key={z.mrgid}
              data-testid={`poe-zone-row-${z.mrgid}`}
              onClick={() => onSelectZone && onSelectZone(z.mrgid, z.bbox, z.anchor)}
              title={z.status === "erreur" && z.last_error ? z.last_error : undefined}
              className={`w-full text-left px-4 py-2.5 border-b border-line hover:bg-raised transition-colors group ${
                isSelected ? "bg-amberx/5 border-l-2 border-l-amberx" : ""
              }`}
            >
              <div className="flex items-start gap-2">
                <span className="text-base leading-none mt-0.5">{flagEmoji(z.iso2 || z.sov_iso2)}</span>
                <div className="flex-1 min-w-0">
                  <div className="font-heading text-sm text-slate-100 truncate group-hover:text-white">
                    {z.name || z.geoname}
                  </div>
                  <div className="font-mono text-[10px] text-slate-500 mt-0.5 truncate">
                    {z.sovereign || "—"}
                    {z.pol_type && z.pol_type !== "200NM" ? ` · ${z.pol_type}` : ""}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                    {statusBadge(z.status)}
                    {z.poe_count > 0 && (
                      <span className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest border-slate-100/50 text-slate-100 bg-slate-100/10">
                        <Anchor size={9} className="inline mr-1 -mt-0.5" />
                        {z.poe_count} {t("poePortsCount")}
                      </span>
                    )}
                    {z.stale && (
                      <span
                        className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest border-amberx/40 bg-amberx/10 text-amberx flex items-center gap-1"
                        title={t("poeStaleTooltip")}
                      >
                        <Clock size={9} /> {t("poeStale")}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Attributions */}
      <div className="px-4 py-2 border-t border-line">
        <p className="font-mono text-[10px] text-slate-300 leading-relaxed">
          {t("poeEezAttribution")} · {t("poeGeocodeAttribution")}
        </p>
      </div>
    </aside>
  );
}
