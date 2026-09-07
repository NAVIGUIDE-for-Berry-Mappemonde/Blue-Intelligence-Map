import { Anchor, ExternalLink, MapPin, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import api from "../api";

const LIST_CAP = 250;

export default function MarinasPanel({
  t,
  marinas,
  onFlyTo,
  onRefresh,
  onRefreshAnchorages,
}) {
  const [query, setQuery] = useState("");
  const batchPollRef = useRef(null);
  const features = marinas?.features || [];

  useEffect(() => {
    let live = true;
    let iv = null;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/anchorages/build/status");
        if (!live) return;
        if (wasRunning && !data.running) {
          if (onRefreshAnchorages) onRefreshAnchorages();
        }
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    iv = setInterval(check, 5000);
    return () => { live = false; if (iv) clearInterval(iv); };
  }, [onRefreshAnchorages]);

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

  useEffect(() => {
    let live = true;
    let iv = null;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/marinas/maps-place/status");
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
    if (!q) return features;
    return features.filter((f) => {
      const p = f.properties || {};
      return (
        (p.name || "").toLowerCase().includes(q)
        || String(p.osm_id || "").toLowerCase().includes(q)
      );
    });
  }, [features, query]);

  const visible = filtered.slice(0, LIST_CAP);
  const truncated = filtered.length > LIST_CAP;

  return (
    <aside className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface" data-testid="marinas-panel">
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-2 mb-3">
          <Anchor size={18} className="text-alert" />
          <h2 className="font-heading font-bold text-white text-base">{t("modeMarinas")}</h2>
          <span className="ml-auto font-mono text-[10px] text-slate-500" data-testid="marinas-count">
            {features.length} {t("marinasCount")}
          </span>
        </div>
        <div className="relative mb-3">
          <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            data-testid="marinas-search-input"
            type="text"
            name="marinas-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("marinasSearch")}
            className="w-full bg-raised border border-line rounded-sm pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent/50"
          />
        </div>

        <div className="mb-1" data-testid="marinas-legend">
          <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-1.5">{t("legend")}</p>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full shrink-0 opacity-70" style={{ background: "#ff4a4a" }} />
              <span className="text-[11px] text-slate-300">{t("legendMarinaWorld")}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-3 rounded-full shrink-0" style={{ background: "#ff4a4a", boxShadow: "0 0 6px #ff4a4a66" }} />
              <span className="text-[11px] text-slate-300">{t("legendMarinaGooglePlace")}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: "#2dd4bf", boxShadow: "0 0 6px #2dd4bf66" }} />
              <span className="text-[11px] text-slate-300">{t("legendAnchorage")}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto" data-testid="marinas-list">
        {features.length === 0 && (
          <div className="p-6 text-center text-xs text-slate-500 leading-relaxed">
            <Anchor size={28} className="mx-auto mb-3 text-slate-600" />
            {t("marinasEmpty")}
          </div>
        )}
        {truncated && (
          <p className="px-4 py-2 font-mono text-[10px] text-slate-500" data-testid="marinas-list-truncated">
            {t("marinasListTruncated").replace("{shown}", String(LIST_CAP)).replace("{total}", String(filtered.length))}
          </p>
        )}
        {visible.map((f) => {
          const p = f.properties || {};
          const [lon, lat] = f.geometry?.coordinates || [0, 0];
          return (
            <button
              key={p.id || p.osm_id}
              data-testid={`marina-row-${p.id}`}
              onClick={() => onFlyTo && onFlyTo(p.id, lat, lon)}
              className="w-full text-left px-4 py-3 border-b border-line hover:bg-raised transition-colors group"
              title={t("marinasFlyTo")}
            >
              <div className="flex items-start gap-2">
                <MapPin size={13} className="text-alert mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-heading text-sm text-slate-100 truncate group-hover:text-white">
                    {p.name || t("marinasUnnamed")}
                  </div>
                  <div className="font-mono text-[10px] text-slate-500 mt-0.5 truncate">
                    {p.osm_id || `${Number(lat).toFixed(3)}, ${Number(lon).toFixed(3)}`}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <span className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest bg-bio/15 text-bio border-bio/40">
                      {t("marinasSourceOSM")}
                    </span>
                    {p.has_google_place && (
                      <span className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest bg-alert/15 text-alert border-alert/40">
                        {t("marinasGooglePlace")}
                      </span>
                    )}
                    {p.website && (
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
          <a
            href="https://www.openstreetmap.org/copyright"
            target="_blank"
            rel="noreferrer"
            className="hover:text-white"
          >
            {t("marinasOdbL")}
          </a>
        </p>
      </div>
    </aside>
  );
}
