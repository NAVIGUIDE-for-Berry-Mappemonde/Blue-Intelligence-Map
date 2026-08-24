import { Anchor, CheckCircle2, ChevronRight, Clock, Download, Globe, Loader2, MapPin, RefreshCw, ScrollText, ShieldCheck, ShieldQuestion } from "lucide-react";
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

const REGIME_LABEL_KEY = {
  metropole:    "formalitiesRegimeMetropole",
  drom:         "formalitiesRegimeDrom",
  com:          "formalitiesRegimeCom",
  taaf:         "formalitiesRegimeTaaf",
  sui_generis:  "formalitiesRegimeSuiGeneris",
};

// Entrée / Sortie / Cas particuliers field key ordering.
const ENTREE_FIELDS = [
  ["preavis",              "formalitiesFieldsPreavis"],
  ["pavillon_q",           "formalitiesFieldsPavillonQ"],
  ["demarches_arrivee",    "formalitiesFieldsDemarchesArrivee"],
  ["ou_s_amarrer",         "formalitiesFieldsOuSAmarrer"],
  ["vhf",                  "formalitiesFieldsVhf"],
  ["douanes_clearance",    "formalitiesFieldsDouanesClearance"],
  ["admission_temporaire", "formalitiesFieldsAdmissionTemporaire"],
  ["franchises",           "formalitiesFieldsFranchises"],
  ["biosecurite",          "formalitiesFieldsBiosecurite"],
  ["frais",                "formalitiesFieldsFrais"],
  ["horaires",             "formalitiesFieldsHoraires"],
];
const SORTIE_FIELDS = [
  ["clearance",   "formalitiesFieldsClearance"],
  ["delais",      "formalitiesFieldsDelais"],
  ["documents",   "formalitiesFieldsDocuments"],
  ["ou_obtenir",  "formalitiesFieldsOuObtenir"],
];
const CAS_PARTICULIERS_FIELDS = [
  ["animaux", "formalitiesFieldsAnimaux"],
  ["drones",  "formalitiesFieldsDrones"],
  ["armes",   "formalitiesFieldsArmes"],
];
const IMMIGRATION_FIELDS = [
  ["visa",             "formalitiesFieldsVisa"],
  ["duree_sejour",     "formalitiesFieldsDureeSejour"],
  ["equivalent_esta",  "formalitiesFieldsEsta"],
  ["notes",            "formalitiesFieldsNotes"],
];

// Phase 5 — nationality selector removed; NATIONALITY_OPTIONS/readInitialNationality
// were used until Phase 4B, kept commented-out here for archaeology. The
// Immigration tab now shows the FR slot only.

/**
 * FormalitiesPanel — Phase 4A sidebar for the third mode.
 *
 * Props :
 *   t                      i18n helper
 *   route                  GeoJSON FeatureCollection (Berry-Mappemonde official)
 *   formalities            [{territory_code, status, escale_overlays, generated_at, ...}]
 *   territories            {territories: [...], blacklist_domains: [...]}
 *   selectedTerritory      territory_code of the currently open card
 *   selectedEscale         escale name currently focused
 *   onSelectEscale         fn(escale_name, territory_code) — sidebar → map
 */
export default function FormalitiesPanel({
  t,
  route,
  formalities,
  territories,
  selectedTerritory,
  selectedEscale,
  onSelectEscale,
  onFormalitiesRefresh,   // fn() — parent will refetch /api/formalities
}) {
  const [activeTab, setActiveTab] = useState("entree");
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  // Phase 4B — batch poller + per-territory refresh state (batch trigger moved to Audit view)
  const batchPollRef = useRef(null);
  const [refreshingCode, setRefreshingCode] = useState(null);   // territory_code being refreshed one-off
  const [refreshFeedback, setRefreshFeedback] = useState(null); // {code, msg, color}
  const [verifying, setVerifying] = useState(false);

  // Build the ordered list of escale rows from route.geojson features order —
  // La Rochelle is intentionally kept twice (départ / retour) per acceptance
  // criterion (a) of the brief. Deduplication is handled by mapping each row
  // to the *same* territory_code so both open the same card.
  const rows = useMemo(() => {
    if (!route?.features || !territories?.territories) return [];
    const escaleFeatures = route.features.filter(
      (f) => f.geometry?.type === "Point" && f.properties?.point_type === "escale",
    );
    // territory lookup by escale name
    const escaleToTerritory = {};
    for (const terr of territories.territories) {
      for (const en of terr.escale_names || []) {
        escaleToTerritory[en] = terr;
      }
    }
    // Formalities lookup by territory_code
    const forByCode = {};
    for (const f of formalities || []) forByCode[f.territory_code] = f;
    // La Rochelle appears twice — tag them départ/retour based on order.
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
      // Find the matching overlay for THIS escale
      const overlay =
        forDoc?.escale_overlays?.find((o) => o.escale_name === name) || null;
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

  // Load the detailed card for the selected territory (with territory_ref embedded)
  useEffect(() => {
    if (!selectedTerritory) {
      setDetail(null);
      return;
    }
    let alive = true;
    setDetailLoading(true);
    api.get(`/formalities/${selectedTerritory}`)
      .then((r) => { if (alive) setDetail(r.data); })
      .catch(() => { if (alive) setDetail(null); })
      .finally(() => { if (alive) setDetailLoading(false); });
    return () => { alive = false; };
  }, [selectedTerritory]);

  // Also reload the detail whenever the underlying formalities collection changes
  // (poll refresh after batch progress).
  useEffect(() => {
    if (!selectedTerritory) return;
    api.get(`/formalities/${selectedTerritory}`)
      .then((r) => setDetail(r.data))
      .catch(() => {});
  }, [formalities, selectedTerritory]);

  // ---------- Phase 4B — Formalities batch poller (kicks off in Audit view) ----------
  // We keep a lightweight poller here so the sidebar + card + map recolour live
  // while the Audit-triggered batch progresses.
  const [batchRunning, setBatchRunning] = useState(false);
  useEffect(() => {
    let alive = true;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/formalities/generate-batch/status");
        if (!alive) return;
        setBatchRunning(!!data.running);
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

  // ---------- Refresh a single territory ----------
  const refreshOne = async (code) => {
    if (refreshingCode) return;
    if (!code || !window.__biGenerateFormality) return;
    setRefreshingCode(code);
    setRefreshFeedback({ code, msg: t("formalitiesRefreshRunning"), color: "#fbbf24" });
    const kick = await window.__biGenerateFormality(code);
    if (!kick.ok && kick.code !== 409) {
      setRefreshFeedback({ code, msg: t("formalitiesRefreshFailed"), color: "#ff4a4a" });
      setRefreshingCode(null);
      return;
    }
    // Poll status ourselves
    for (let i = 0; i < 120; i++) {
      await new Promise((res) => setTimeout(res, 3000));
      try {
        const st = await api.get(`/formalities/${code}/generate/status`);
        if (st.data?.state === "done") {
          setRefreshFeedback({ code, msg: t("formalitiesRefreshDone"), color: "#39ff14" });
          if (onFormalitiesRefresh) onFormalitiesRefresh();
          break;
        }
        if (st.data?.state === "error") {
          setRefreshFeedback({ code, msg: t("formalitiesRefreshFailed"), color: "#ff4a4a" });
          break;
        }
      } catch (_) { /* transient */ }
    }
    setRefreshingCode(null);
  };

  // ---------- Verify (crew mark as verified) ----------
  const verifyCurrent = async () => {
    if (!selectedTerritory || verifying) return;
    setVerifying(true);
    try {
      const r = await window.__biVerifyFormality?.(selectedTerritory);
      if (r?.ok) {
        // Refresh the local detail
        const fresh = await api.get(`/formalities/${selectedTerritory}`);
        setDetail(fresh.data);
      }
    } finally {
      setVerifying(false);
    }
  };

  const escaleCount = rows.length;

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

  const renderPlaceholder = () => (
    <div className="italic text-slate-500 text-xs leading-relaxed p-3 bg-raised/40 border border-line rounded-sm">
      {t("formalitiesNotGenerated")}
    </div>
  );

  const renderFieldGroup = (source, keys) => {
    if (!source) return renderPlaceholder();
    const hasAny = keys.some(([k]) => source[k] !== null && source[k] !== undefined && source[k] !== "");
    if (!hasAny) return renderPlaceholder();
    return (
      <dl className="space-y-2">
        {keys.map(([k, labelKey]) => {
          const v = source[k];
          if (v === null || v === undefined || v === "") return null;
          return (
            <div key={k}>
              <dt className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-0.5">{t(labelKey)}</dt>
              <dd className="text-xs text-slate-200 leading-relaxed">{String(v)}</dd>
            </div>
          );
        })}
      </dl>
    );
  };

  const renderCard = () => {
    if (!detail) {
      return (
        <div className="p-6 text-center text-xs text-slate-500 leading-relaxed">
          <ScrollText size={28} className="mx-auto mb-3 text-slate-600" />
          {t("formalitiesSelectHint")}
        </div>
      );
    }
    const terr = detail.territory || {};
    const overlay = selectedEscale
      ? (detail.escale_overlays || []).find((o) => o.escale_name === selectedEscale)
      : null;
    const regimeLabel = t(REGIME_LABEL_KEY[terr.regime] || "formalitiesRegimeMetropole");
    const isBusy = refreshingCode === terr.code;
    const showFeedback = refreshFeedback && refreshFeedback.code === terr.code;
    const canVerify = detail.status === "ia" || detail.status === "ia_sans_source";
    return (
      <div className="p-3 space-y-3" data-testid="formalities-card">
        {/* Title + status + regime + actions */}
        <div>
          <div className="flex items-start gap-2">
            <span className="text-xl leading-none">{terr.flag_emoji || "🏳️"}</span>
            <div className="flex-1 min-w-0">
              <h3 className="font-heading font-bold text-slate-100 text-sm leading-tight">
                {terr.name_fr || terr.code}
              </h3>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {renderStatusBadge(detail.status)}
                <span className="px-1.5 py-0.5 border border-line rounded-sm font-mono text-[9px] uppercase tracking-widest text-slate-400">
                  {regimeLabel}
                </span>
                {detail.stale && (
                  <span
                    data-testid="formalities-stale-badge"
                    title={t("formalitiesStaleTooltip")}
                    className="px-1.5 py-0.5 border border-amberx/50 bg-amberx/10 text-amberx rounded-sm font-mono text-[9px] uppercase tracking-widest flex items-center gap-1"
                  >
                    <Clock size={9} /> {t("formalitiesStale")}
                  </span>
                )}
              </div>
              {detail.generated_at && (
                <div className="mt-1 font-mono text-[9px] text-slate-500">
                  {t("formalitiesGeneratedAt")}: {detail.generated_at.slice(0, 10)}
                  {detail.verified_at && (
                    <span className="ml-2 text-bio">
                      · {t("formalitiesVerifiedAt")}: {detail.verified_at.slice(0, 10)}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
          {/* Action buttons */}
          <div className="mt-2 flex items-center gap-1.5 flex-wrap">
            <button
              data-testid="formalities-refresh-btn"
              onClick={() => refreshOne(terr.code)}
              disabled={isBusy || batchRunning}
              className="flex items-center gap-1 px-2 py-1 border border-amberx/40 bg-amberx/10 hover:bg-amberx/15 disabled:opacity-60 disabled:cursor-not-allowed text-amberx font-mono text-[10px] uppercase tracking-wider rounded-sm"
              title={t("formalitiesRefreshBtn")}
            >
              {isBusy
                ? <><Loader2 size={10} className="animate-spin" /> {t("formalitiesRefreshRunning")}</>
                : <><RefreshCw size={10} /> {t("formalitiesRefreshBtn")}</>}
            </button>
            {canVerify && (
              <button
                data-testid="formalities-verify-btn"
                onClick={verifyCurrent}
                disabled={verifying}
                className="flex items-center gap-1 px-2 py-1 border border-bio/40 bg-bio/10 hover:bg-bio/15 disabled:opacity-60 disabled:cursor-not-allowed text-bio font-mono text-[10px] uppercase tracking-wider rounded-sm"
                title={t("formalitiesVerifyBtnTooltip")}
              >
                {verifying
                  ? <><Loader2 size={10} className="animate-spin" /> …</>
                  : <><CheckCircle2 size={10} /> {t("formalitiesVerifyBtn")}</>}
              </button>
            )}
            {showFeedback && (
              <span
                className="font-mono text-[10px]"
                style={{ color: refreshFeedback.color }}
              >
                {refreshFeedback.msg}
              </span>
            )}
          </div>
        </div>

        {/* Overlay of selected escale */}
        {overlay && (
          <div
            className="p-2 border border-line bg-raised/40 rounded-sm text-[11px] leading-relaxed"
            data-testid="formalities-escale-overlay"
          >
            <div className="flex items-center gap-2 mb-1">
              <MapPin size={12} className="text-slate-400" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-slate-500">
                {t("formalitiesEscaleOverlay")}
              </span>
              {renderPoeBadge(!!overlay.is_port_of_entry)}
            </div>
            <div className="text-slate-100 font-heading text-xs">{overlay.escale_name}</div>
            {overlay.note && (
              <div className="text-slate-400 mt-1">{overlay.note}</div>
            )}
          </div>
        )}

        {/* Tabs */}
        <div className="border-b border-line flex gap-0.5 overflow-x-auto -mx-3 px-3">
          {[
            ["entree",           "formalitiesTabEntree"],
            ["sortie",           "formalitiesTabSortie"],
            ["cas_particuliers", "formalitiesTabCasParticuliers"],
            ["immigration",      "formalitiesTabImmigration"],
            ["contacts",         "formalitiesTabContacts"],
            ["sources",          "formalitiesTabSources"],
          ].map(([id, labelKey]) => (
            <button
              key={id}
              data-testid={`formalities-tab-${id}`}
              onClick={() => setActiveTab(id)}
              className={`px-2.5 py-1.5 text-[11px] font-semibold whitespace-nowrap border-b-2 -mb-px ${
                activeTab === id
                  ? "border-amberx text-amberx"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div data-testid={`formalities-tab-content-${activeTab}`}>
          {activeTab === "entree" && renderFieldGroup(detail.entree, ENTREE_FIELDS)}
          {activeTab === "sortie" && renderFieldGroup(detail.sortie, SORTIE_FIELDS)}
          {activeTab === "cas_particuliers" && renderFieldGroup(detail.cas_particuliers, CAS_PARTICULIERS_FIELDS)}
          {activeTab === "immigration" && (() => {
            // Phase 5 — only the FR slot is exposed; ca/us/gb generation was abandoned.
            const slot = (detail.immigration || {}).fr;
            if (!slot) return renderPlaceholder();
            return renderFieldGroup(slot, IMMIGRATION_FIELDS);
          })()}
          {activeTab === "contacts" && (
            (detail.contacts || []).length === 0 && (detail.liens_officiels || []).length === 0
              ? renderPlaceholder()
              : (
                <div className="space-y-2 text-xs">
                  {(detail.contacts || []).map((c, i) => (
                    <div key={i} className="text-slate-200">
                      <span className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mr-2">{c.type}</span>
                      {c.label}: <span className="text-slate-100">{c.value}</span>
                    </div>
                  ))}
                  {(detail.liens_officiels || []).map((l, i) => (
                    <a
                      key={i}
                      href={l.url}
                      target="_blank"
                      rel="noreferrer"
                      className="block text-sonar text-xs hover:underline break-all"
                    >
                      {l.label} →
                    </a>
                  ))}
                </div>
              )
          )}
          {activeTab === "sources" && (() => {
            const srcs = detail.sources || [];
            const isNoSource = detail.status === "ia_sans_source";
            return (
              <div className="space-y-2">
                {isNoSource && (
                  <div
                    data-testid="formalities-no-source-warning"
                    className="p-2 bg-alert/10 border border-alert/40 text-alert rounded-sm text-[11px] leading-relaxed"
                  >
                    ⚠️ {t("formalitiesNoSourceWarning")}
                  </div>
                )}
                {srcs.length === 0 ? (
                  <div className="italic text-slate-500 text-xs leading-relaxed p-3 bg-raised/40 border border-line rounded-sm">
                    {t("formalitiesNoSourceEmpty")}
                  </div>
                ) : (
                  <ul className="space-y-1.5 text-xs">
                    {srcs.map((s, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <Globe size={11} className="text-slate-500 mt-0.5 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <a href={s.url} target="_blank" rel="noreferrer" className="text-sonar hover:underline break-all text-[11px]">
                            {s.url}
                          </a>
                          <div className="font-mono text-[9px] text-slate-500 mt-0.5">
                            {s.domain}
                            {s.collected_at && <span className="ml-2">· {s.collected_at.slice(0, 10)}</span>}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })()}
        </div>

        {/* Territory footer — official domains hint (always shown at bottom) */}
        {terr.official_domains?.length > 0 && (
          <div className="mt-3 pt-2 border-t border-line">
            <div className="flex items-center gap-2 mb-1">
              <Globe size={11} className="text-slate-500" />
              <span className="font-mono text-[9px] uppercase tracking-widest text-slate-500">
                {t("formalitiesOfficialDomains")}
              </span>
            </div>
            <div className="flex flex-wrap gap-1">
              {terr.official_domains.slice(0, 6).map((d) => (
                <span
                  key={d}
                  className="px-1.5 py-0.5 border border-line rounded-sm font-mono text-[9px] text-slate-400"
                >
                  {d}
                </span>
              ))}
              {terr.official_domains.length > 6 && (
                <span className="font-mono text-[9px] text-slate-500 self-center">
                  +{terr.official_domains.length - 6}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <aside
      className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface"
      data-testid="formalities-panel"
    >
      {/* Header block */}
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-2 mb-2">
          <ScrollText size={18} className="text-amberx" />
          <h2 className="font-heading font-bold text-white text-base">{t("modeFormalities")}</h2>
          <span className="ml-auto font-mono text-[10px] text-amberx/80 uppercase tracking-widest">
            {escaleCount} {t("formalitiesCount")}
          </span>
        </div>
        <p className="font-mono text-[10px] uppercase tracking-[0.15em] text-slate-500 mb-3">
          {t("formalitiesSubtitle")}
        </p>

        {/* Permanent disclaimer */}
        <div
          data-testid="formalities-disclaimer"
          className="bi-formalities-disclaimer text-[11px] leading-relaxed px-2.5 py-2 rounded-sm mb-3"
        >
          ⚠️ {t("formalitiesDisclaimer")}
        </div>

        {/* Phase 5 — nationality selector removed. Immigration tab now shows FR only. */}

        {/* Phase 5 — Batch generation moved to Audit view. Sidebar keeps
            per-fiche refresh/verify. Contextual export button below. */}
        <div className="mt-3 pt-3 border-t border-line flex items-center justify-between gap-2">
          <span className="font-mono text-[10px] uppercase tracking-widest text-slate-500 flex-1">
            {t("formalitiesBatchMovedToAudit")}
          </span>
          <a
            data-testid="formalities-export-btn"
            href={`${process.env.REACT_APP_BACKEND_URL}/api/export/formalities.geojson`}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-accent/40 bg-accent/10 hover:bg-accent/20 text-accent font-semibold text-xs rounded-sm"
            title={t("exportGeoJsonTooltip")}
          >
            <Download size={12} /> {t("exportGeoJson")}
          </a>
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

      {/* Detailed card (bottom pinned) */}
      {selectedTerritory && (
        <div className="border-t border-line max-h-[55vh] overflow-y-auto" data-testid="formalities-card-wrap">
          {detailLoading && (
            <div className="p-4 text-xs text-slate-500 font-mono">Loading…</div>
          )}
          {!detailLoading && renderCard()}
        </div>
      )}
    </aside>
  );
}
