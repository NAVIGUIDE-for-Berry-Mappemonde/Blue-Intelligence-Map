import { Anchor, ChevronRight, Clock, ScrollText, ShieldCheck, ShieldQuestion } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import api from "../api";

// --- Status → colour tokens (kept in sync with MapView escale colours) ---
const STATUS_COLOR = {
  non_generee:     "bg-slate-500/15 text-slate-300 border-slate-500/40",
  ia:              "bg-amberx/15 text-amberx border-amberx/40",
  ia_sans_source:  "bg-amberx/10 text-amberx border-amberx/40 border-dashed",
  verifiee:        "bg-bio/15 text-bio border-bio/40",
};
const STATUS_LABEL_KEY = {
  non_generee:    "formalitiesStatusNonGeneree",
  ia:             "formalitiesStatusIa",
  ia_sans_source: "formalitiesStatusIaSansSource",
  verifiee:       "formalitiesStatusVerifiee",
};

/**
 * FormalitiesPanel — Phase 6 slim sidebar.
 *
 * The sidebar keeps ONLY:
 *   - the ordered list of the 17 escales (status pill + PoE badge)
 *   - the permanent disclaimer
 *   - a batch-moved-to-Audit hint
 *
 * The full fiche (all sections) is now rendered in the MAP POPUP of the
 * corresponding territory. Clicking a row here centres the map on the escale
 * AND opens the popup.
 */
export default function FormalitiesPanel({
  t,
  route,
  formalities,
  territories,
  selectedTerritory,
  selectedEscale,
  onSelectEscale,
  onFormalitiesRefresh,
}) {
  const batchPollRef = useRef(null);

  // Phase 8 ZEE crossings — moved to the Swarm Intelligence Audit panel
  // (BatchHub formalities card) per user request, 2026-06.

  const rows = useMemo(() => {
    if (!route?.features || !territories?.territories) return [];
    const escaleFeatures = route.features.filter(
      (f) => f.geometry?.type === "Point" && f.properties?.point_type === "escale",
    );
    const escaleToTerritory = {};
    for (const terr of territories.territories) {
      for (const en of terr.escale_names || []) {
        escaleToTerritory[en] = terr;
      }
    }
    const forByCode = {};
    for (const f of formalities || []) forByCode[f.territory_code] = f;
    const laRochelleSeen = { count: 0 };
    return escaleFeatures.map((feat, idx) => {
      const name = feat.properties.name;
      const terr = escaleToTerritory[name];
      const forDoc = terr ? forByCode[terr.code] : null;
      let leg = null;
      if (name === "La Rochelle") {
        laRochelleSeen.count += 1;
        leg = laRochelleSeen.count === 1 ? "departure" : "return";
      }
      const overlay = forDoc?.escale_overlays?.find((o) => o.escale_name === name) || null;
      return {
        key: `${name}::${idx}`,
        escaleName: name,
        territory: terr,
        formality: forDoc,
        overlay,
        leg,
        coord: feat.geometry.coordinates, // [lon, lat]
      };
    });
  }, [route, territories, formalities]);

  // Phase 6 — poll the batch status only to refresh the collection while a
  // batch is running (map popup + row colours must update live).
  useEffect(() => {
    let alive = true;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/formalities/generate-batch/status");
        if (!alive) return;
        if (data.running) {
          if (onFormalitiesRefresh) onFormalitiesRefresh();
        } else if (wasRunning && onFormalitiesRefresh) {
          onFormalitiesRefresh();
        }
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    batchPollRef.current = setInterval(check, 3000);
    return () => {
      alive = false;
      if (batchPollRef.current) clearInterval(batchPollRef.current);
    };
  }, [onFormalitiesRefresh]);

  // Selected row highlighter — the selectedTerritory/selectedEscale props are
  // used inline in the rows map below (see isSelected computation).

  const escaleCount = rows.length; // eslint-disable-line no-unused-vars

  const renderStatusBadge = (status) => {
    const cls = STATUS_COLOR[status] || STATUS_COLOR.non_generee;
    const label = t(STATUS_LABEL_KEY[status] || "formalitiesStatusNonGeneree");
    return (
      <span className={`px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest ${cls}`}>
        {label}
      </span>
    );
  };

  const renderPoeBadge = (isPoe) => {
    if (isPoe) {
      return (
        <span
          className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest border-slate-100/70 text-slate-100 bg-slate-100/10"
          title={t("formalitiesPortOfEntry")}
        >
          <Anchor size={9} className="inline mr-1 -mt-0.5" />
          {t("formalitiesPortOfEntry")}
        </span>
      );
    }
    return (
      <span
        className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest border-slate-600 text-slate-500"
        title={t("formalitiesNotPortOfEntry")}
      >
        {t("formalitiesNotPortOfEntry")}
      </span>
    );
  };

  return (
    <aside
      className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface"
      data-testid="formalities-panel"
    >
      {/* Header block — Phase 6: title + count + disclaimer only. */}
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-2 mb-2">
          <ScrollText size={18} className="text-amberx" />
          <h2 className="font-heading font-bold text-white text-base">{t("modeFormalities")}</h2>
          {/* Count removed 2026-06 (UX): duplicated the ITEMS MAPPED dashboard KPI */}
        </div>

        {/* Permanent disclaimer */}
        <div
          data-testid="formalities-disclaimer"
          className="bi-formalities-disclaimer text-[11px] leading-relaxed px-2.5 py-2 rounded-sm mb-2"
        >
          ⚠️ {t("formalitiesDisclaimer")}
        </div>

        <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
          {t("formalitiesPopupHint")}
        </p>
        {/* ZEE crossings section moved to the SIA formalities card (2026-06) */}
      </div>

      {/* Escales list */}
      <div className="flex-1 overflow-y-auto" data-testid="formalities-list">
        {rows.length === 0 && (
          <div className="p-6 text-center text-xs text-slate-500 leading-relaxed">
            <ScrollText size={28} className="mx-auto mb-3 text-slate-600" />
            {t("formalitiesEmpty")}
          </div>
        )}
        {rows.map((row) => {
          const status = row.formality?.status || "non_generee";
          const isSelected =
            selectedTerritory && row.territory?.code === selectedTerritory &&
            (!selectedEscale || selectedEscale === row.escaleName);
          const isPoe = !!row.overlay?.is_port_of_entry;
          return (
            <button
              key={row.key}
              data-testid={`formalities-row-${row.territory?.code || "unknown"}${row.leg ? "-" + row.leg : ""}`}
              onClick={() => row.territory && onSelectEscale(row.escaleName, row.territory.code, row.coord)}
              className={`w-full text-left px-4 py-3 border-b border-line hover:bg-raised transition-colors group ${
                isSelected ? "bg-amberx/5 border-l-2 border-l-amberx" : ""
              }`}
            >
              <div className="flex items-start gap-2">
                {isPoe
                  ? <ShieldCheck size={14} className="text-slate-100 mt-0.5 shrink-0" />
                  : <ShieldQuestion size={14} className="text-slate-500 mt-0.5 shrink-0" />}
                <div className="flex-1 min-w-0">
                  <div className="font-heading text-sm text-slate-100 truncate group-hover:text-white flex items-center gap-1.5">
                    <span className="text-base leading-none">{row.territory?.flag_emoji || "🏳️"}</span>
                    <span className="truncate">{row.escaleName}</span>
                    {row.leg && (
                      <span className="ml-1 font-mono text-[9px] px-1 py-0.5 border border-slate-600 rounded-sm text-slate-400 shrink-0">
                        {row.leg === "departure" ? t("formalitiesLegDeparture") : t("formalitiesLegReturn")}
                      </span>
                    )}
                  </div>
                  <div className="font-mono text-[10px] text-slate-500 mt-0.5 truncate">
                    {row.territory?.name_fr || "—"}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1.5">
                    {renderStatusBadge(status)}
                    {renderPoeBadge(isPoe)}
                    {row.formality?.stale && (
                      <span
                        className="px-1.5 py-0.5 border rounded-sm font-mono text-[9px] uppercase tracking-widest border-amberx/40 bg-amberx/10 text-amberx flex items-center gap-1"
                        title={t("formalitiesStaleTooltip")}
                      >
                        <Clock size={9} /> {t("formalitiesStale")}
                      </span>
                    )}
                  </div>
                </div>
                <ChevronRight size={14} className="text-slate-600 shrink-0 mt-1" />
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
