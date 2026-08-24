import { Anchor, ChevronRight, Clock, Loader2, Radar, ScrollText, ShieldCheck, ShieldQuestion, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
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

  // ---- Phase 8 — ZEE crossings ----
  const [zee, setZee] = useState(null);            // GET /zee/crossings payload
  const [zeeLoading, setZeeLoading] = useState(true);
  const [zeeComputing, setZeeComputing] = useState(false);
  const [zeeError, setZeeError] = useState(null);
  const [zeeTriggering, setZeeTriggering] = useState(false);
  const [zeeTriggerResult, setZeeTriggerResult] = useState(null);

  const territoryByCode = useMemo(() => {
    const acc = {};
    for (const terr of territories?.territories || []) acc[terr.code] = terr;
    return acc;
  }, [territories]);

  const fetchZee = async () => {
    try {
      const { data } = await api.get("/zee/crossings");
      setZee(data);
      setZeeError(null);
    } catch (e) {
      // 404 = not computed yet (expected); surface any other failure
      if (e?.response?.status !== 404) setZeeError(e?.message || "request failed");
    } finally {
      setZeeLoading(false);
    }
  };
  useEffect(() => { fetchZee(); }, []);

  const detectZee = async () => {
    if (zeeComputing) return;
    setZeeError(null);
    setZeeComputing(true);
    try {
      await api.post("/zee/compute", {});
    } catch (e) {
      if (e?.response?.status !== 409) {
        setZeeError(e?.message || "failed");
        setZeeComputing(false);
        return;
      }
    }
    // Poll status until done (max ~5 min — first run downloads/parses EEZ polygons)
    for (let i = 0; i < 150; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const { data } = await api.get("/zee/compute/status");
        if (!data.running) {
          if (data.error) setZeeError(data.error);
          await fetchZee();
          break;
        }
      } catch (_) { /* transient */ }
    }
    setZeeComputing(false);
  };

  const triggerZeeFormalities = async () => {
    if (zeeTriggering) return;
    setZeeTriggering(true);
    setZeeTriggerResult(null);
    try {
      const { data } = await api.post("/zee/trigger-formalities");
      setZeeTriggerResult(data);
      if (onFormalitiesRefresh) onFormalitiesRefresh();
    } catch (e) {
      setZeeTriggerResult({ error: e?.message || "failed" });
    } finally {
      setZeeTriggering(false);
    }
  };

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

        {/* Phase 8 — ZEE crossings detection */}
        <div className="mt-3 pt-3 border-t border-line" data-testid="zee-section">
          <div className="flex items-center gap-2 mb-2">
            <Radar size={13} className="text-amberx" />
            <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">{t("zeeTitle")}</span>
            {zee?.summary && (
              <span className="ml-auto font-mono text-[9px] text-slate-500" data-testid="zee-summary">
                {zee.summary.total_crossings} {t("zeeCrossings")} · {zee.summary.unique_territories} {t("zeeTerritories")}
              </span>
            )}
          </div>
          <button
            data-testid="zee-detect-btn"
            onClick={detectZee}
            disabled={zeeComputing}
            className="w-full flex items-center justify-center gap-2 px-3 py-1.5 border border-amberx/40 bg-amberx/10 hover:bg-amberx/20 disabled:opacity-60 disabled:cursor-not-allowed text-amberx font-semibold text-xs rounded-sm"
          >
            {zeeComputing
              ? <><Loader2 size={12} className="animate-spin" /> {t("zeeDetecting")}</>
              : <><Radar size={12} /> {t("zeeDetect")}</>}
          </button>
          {zeeError && (
            <p className="mt-1.5 text-[10px] text-alert font-mono" data-testid="zee-error">{t("zeeError")}: {String(zeeError).slice(0, 120)}</p>
          )}
          {zeeLoading && !zee && (
            <p className="mt-1.5 text-[10px] text-slate-500 font-mono animate-pulse">…</p>
          )}
          {!zee && !zeeLoading && !zeeComputing && !zeeError && (
            <p className="mt-1.5 text-[10px] text-slate-500 leading-relaxed">{t("zeeEmpty")}</p>
          )}
          {zee?.crossings?.length > 0 && (
            <>
              <div
                className="mt-2 max-h-72 overflow-y-auto border border-line rounded-sm bg-abyss/50 divide-y divide-line/60"
                data-testid="zee-crossings-list"
              >
                {zee.crossings.map((c) => {
                  const terr = c.territory_code ? territoryByCode[c.territory_code] : null;
                  const isFr = !!c.territory_code;
                  return (
                    <div key={`${c.order}-${c.geoname}`} className="px-2 py-1.5 flex items-start gap-1.5">
                      <span className="font-mono text-[9px] text-slate-600 mt-0.5 w-5 shrink-0">#{c.order}</span>
                      <span className="text-sm leading-none mt-0.5 shrink-0">{terr?.flag_emoji || "🌐"}</span>
                      <div className="flex-1 min-w-0">
                        <div className={`text-[11px] truncate ${isFr ? "text-slate-100" : "text-slate-400"}`}>
                          {terr?.name_fr || c.geoname}
                        </div>
                        <div className="font-mono text-[9px] text-slate-500 truncate">
                          {isFr ? (c.pol_type && c.pol_type !== "200NM" ? c.pol_type : "ZEE FR") : `${t("zeeForeign")} · ${c.sovereign || ""}`}
                          {" · "}{t("zeeEntry")} {Number(c.entry_lat).toFixed(2)},{Number(c.entry_lon).toFixed(2)}
                          {c.intersection_length_nm ? ` · ~${Math.round(c.intersection_length_nm)} NM` : ""}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
              <button
                data-testid="zee-trigger-btn"
                onClick={triggerZeeFormalities}
                disabled={zeeTriggering}
                className="mt-2 w-full flex items-center justify-center gap-2 px-3 py-1.5 border border-bio/40 bg-bio/10 hover:bg-bio/20 disabled:opacity-60 disabled:cursor-not-allowed text-bio font-semibold text-[11px] rounded-sm"
              >
                {zeeTriggering
                  ? <><Loader2 size={12} className="animate-spin" /> {t("zeeTriggering")}</>
                  : <><Sparkles size={12} /> {t("zeeTrigger")}</>}
              </button>
              {zeeTriggerResult && !zeeTriggerResult.error && (
                <p className="mt-1.5 text-[9px] font-mono text-slate-400 leading-relaxed" data-testid="zee-trigger-result">
                  ✓ {zeeTriggerResult.triggered?.length || 0} {t("zeeTriggered")} · {zeeTriggerResult.skipped_uptodate?.length || 0} {t("zeeUpToDate")}
                </p>
              )}
              {zeeTriggerResult?.error && (
                <p className="mt-1.5 text-[9px] font-mono text-alert">{String(zeeTriggerResult.error).slice(0, 100)}</p>
              )}
            </>
          )}
        </div>
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
