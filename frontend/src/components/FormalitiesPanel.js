import { Anchor, ChevronRight, Globe, MapPin, ScrollText, ShieldCheck, ShieldQuestion } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
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

const NATIONALITY_OPTIONS = [
  { code: "fr", labelKey: "formalitiesNationalityFr" },
  { code: "ca", labelKey: "formalitiesNationalityCa" },
  { code: "us", labelKey: "formalitiesNationalityUs" },
  { code: "gb", labelKey: "formalitiesNationalityGb" },
];

/** Persistence helpers for the global nationality selector. */
const readInitialNationality = () => {
  try {
    const v = localStorage.getItem("bi.nationality");
    if (v && ["fr", "ca", "us", "gb"].includes(v)) return v;
  } catch (_) {
    /* localStorage disabled */
  }
  return "fr";
};

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
}) {
  const [nationality, setNationalityRaw] = useState(readInitialNationality());
  const [activeTab, setActiveTab] = useState("entree");
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const setNationality = (v) => {
    setNationalityRaw(v);
    try { localStorage.setItem("bi.nationality", v); } catch (_) { /* ignore */ }
  };

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
    return (
      <div className="p-3 space-y-3" data-testid="formalities-card">
        {/* Title + status + regime */}
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
              </div>
            </div>
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
            const slot = detail.immigration ? detail.immigration[nationality] : null;
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
          {activeTab === "sources" && (
            (detail.sources || []).length === 0
              ? renderPlaceholder()
              : (
                <ul className="space-y-1 text-xs">
                  {detail.sources.map((s, i) => (
                    <li key={i}>
                      <a href={s.url} target="_blank" rel="noreferrer" className="text-sonar hover:underline break-all">
                        {s.domain || s.url}
                      </a>
                      {s.collected_at && (
                        <span className="text-slate-500 font-mono ml-2 text-[10px]">· {s.collected_at.slice(0, 10)}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )
          )}
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

        {/* Nationality selector */}
        <div>
          <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
            {t("formalitiesNationalityLabel")}
          </label>
          <select
            data-testid="nationality-selector"
            value={nationality}
            onChange={(e) => setNationality(e.target.value)}
            className="w-full px-2 py-1.5 bg-raised border border-line rounded-sm text-xs text-slate-100 focus:outline-none focus:border-amberx/60"
          >
            {NATIONALITY_OPTIONS.map((opt) => (
              <option key={opt.code} value={opt.code}>{t(opt.labelKey)}</option>
            ))}
          </select>
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
