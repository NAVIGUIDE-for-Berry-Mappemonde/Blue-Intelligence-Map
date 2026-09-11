import { Search, Shield } from "lucide-react";
import { useMemo, useState } from "react";
import { LFP_COLORS } from "./map/constants";

const LIST_CAP = 80;

export default function AmpPanel({ t, sites, sitesLoading, onFlyTo, lfpFilter = "All", onLfpFilter }) {
  const [q, setQ] = useState("");
  const setLfpFilter = onLfpFilter || (() => {});

  const features = sites?.features || [];
  const hint = sites?.hint;
  const truncated = Boolean(sites?.truncated);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return features.filter((f) => {
      const p = f.properties || {};
      if (lfpFilter !== "All" && String(p.lfp ?? 0) !== String(lfpFilter)) return false;
      if (!needle) return true;
      const hay = `${p.name || ""} ${p.country || ""} ${p.designation || ""} ${p.managing_authority || ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [features, q, lfpFilter]);

  const visible = filtered.slice(0, LIST_CAP);

  return (
    <aside className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface min-h-0" data-testid="amp-panel">
      <div className="p-4 border-b border-line shrink-0">
        <div className="flex items-center gap-2 mb-3">
          <Shield size={18} className="text-[#4ade80]" />
          <h2 className="font-heading font-bold text-white text-base">{t("modeAmp")}</h2>
          <span className="font-mono text-[10px] text-slate-500">· ProtectedSeas</span>
          <span className="ml-auto font-mono text-[10px] text-slate-500" data-testid="amp-count">
            {features.length} {t("ampCount")}
          </span>
        </div>

        <div data-testid="amp-disclaimer" className="bi-amp-disclaimer text-[11px] leading-relaxed px-2.5 py-2 rounded-sm mb-3">
          ⚠️ {t("mpaDisclaimer")}
        </div>

        <div className="relative mb-3">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            data-testid="amp-search-input"
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("ampSearch")}
            className="w-full bg-raised border border-line rounded-sm pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent/50"
          />
        </div>

        <div className="flex flex-wrap gap-1 mb-3">
          <button
            type="button"
            data-testid="amp-lfp-all"
            onClick={() => setLfpFilter("All")}
            className={`px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase ${
              lfpFilter === "All" ? "border-accent/50 bg-accent/15 text-accent" : "border-line text-slate-400"
            }`}
          >
            {t("ampAllLfp")}
          </button>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              data-testid={`amp-lfp-${n}`}
              onClick={() => setLfpFilter(String(n))}
              className={`px-1.5 py-0.5 border rounded-sm font-mono text-[9px] ${
                lfpFilter === String(n) ? "border-accent/50 bg-accent/15 text-accent" : "border-line text-slate-400"
              }`}
              style={{ borderColor: lfpFilter === String(n) ? undefined : `${LFP_COLORS[n]}55` }}
            >
              LFP {n}
            </button>
          ))}
        </div>

        <div data-testid="amp-legend">
          <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-1.5">{t("legend")}</p>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: LFP_COLORS[5] }} />
              <span className="text-[11px] text-slate-300">{t("lfp5")}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: LFP_COLORS[3] }} />
              <span className="text-[11px] text-slate-300">{t("lfp3")}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: LFP_COLORS[1] }} />
              <span className="text-[11px] text-slate-300">{t("lfp1")}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto" data-testid="amp-list">
        {hint === "zoom" && (
          <p className="p-6 text-center text-xs text-slate-500 leading-relaxed" data-testid="amp-zoom-hint">
            {t("mpaZoomHint")}
          </p>
        )}
        {hint !== "zoom" && features.length === 0 && (
          <p className="p-6 text-center text-xs text-slate-500 leading-relaxed">
            {sitesLoading ? t("ampLoading") : t("ampEmpty")}
          </p>
        )}
        {truncated && (
          <p className="px-4 py-2 font-mono text-[10px] text-slate-500">{t("ampTruncated")}</p>
        )}
        {visible.map((f) => {
          const p = f.properties || {};
          return (
            <button
              key={p.site_id || p.id}
              type="button"
              data-testid={`amp-row-${p.site_id || p.id}`}
              onClick={() => onFlyTo && onFlyTo(p.site_id || p.id, p.lat, p.lon)}
              className="w-full text-left px-4 py-3 border-b border-line hover:bg-raised transition-colors group"
            >
              <div className="flex items-start gap-2">
                <span
                  className="mt-1.5 w-2 h-2 rounded-sm shrink-0"
                  style={{ background: LFP_COLORS[Number(p.lfp) || 0] }}
                />
                <div className="min-w-0 flex-1">
                  <p className="font-heading text-sm text-slate-100 truncate group-hover:text-white">{p.name}</p>
                  <p className="font-mono text-[10px] text-slate-500 truncate">
                    {p.country}{p.designation ? ` · ${p.designation}` : ""}
                  </p>
                  <p className="mt-1 font-mono text-[9px] uppercase tracking-wide">
                    <span className="text-slate-500">{t("ampManagerUrl")}</span>
                    {" · "}
                    {p.visit_url
                      ? <span className="text-[#4ade80]">{t("ampVisitFound")}</span>
                      : <span className="text-slate-600">{t("ampVisitMissing")}</span>}
                  </p>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
