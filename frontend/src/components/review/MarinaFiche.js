import { FicheSection, FicheShell, KeepDrop, UrlKeepRow } from "./choiceUi";

const FIELD_KEYS = [
  ["canal_vhf", "VHF"],
  ["places_visiteurs", "reviewPlaces"],
  ["tirant_eau_max_metres", "reviewDraft"],
  ["telephone_capitainerie", "reviewPhone"],
  ["services_disponibles", "reviewServices"],
];

export default function MarinaFiche({ t, fiche, choices, onChoice }) {
  if (!fiche) return null;
  const selectable = typeof onChoice === "function";
  const tags = fiche.tags || {};
  const wp = fiche.nearest_waypoint || {};
  const urlMap = choices?.urls || {};
  const fieldMap = choices?.fields || {};
  const urls = [];
  if (fiche.website) urls.push({ url: fiche.website, key: "website" });
  if (fiche.maps_place_url) urls.push({ url: fiche.maps_place_url, key: "maps" });
  const services = Array.isArray(fiche.services_disponibles)
    ? fiche.services_disponibles.join(", ")
    : (fiche.services_disponibles || "");
  const fieldValues = {
    canal_vhf: fiche.canal_vhf,
    places_visiteurs: fiche.places_visiteurs,
    tirant_eau_max_metres: fiche.tirant_eau_max_metres != null ? `${fiche.tirant_eau_max_metres} m` : null,
    telephone_capitainerie: fiche.telephone_capitainerie,
    services_disponibles: services,
  };
  return (
    <FicheShell
      testId="review-fiche-marina"
      kindLabel={t("reviewKindMarina")}
      title={fiche.name}
      subtitle={[fiche.source, fiche.osm_id ? `OSM ${fiche.osm_id}` : null, fiche.priority != null ? `P${fiche.priority}` : null].filter(Boolean).join(" · ")}
    >
      <FicheSection label={t("reviewIdentity")} testId="review-marina-identity">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs text-slate-300 leading-snug">{t("reviewMarinaIdentityHint")}</p>
          {selectable ? (
            <KeepDrop
              t={t}
              verdict={choices?.identity}
              keepTestId="review-marina-identity-keep"
              dropTestId="review-marina-identity-drop"
              onKeep={() => onChoice({
                target: "identity",
                action: choices?.identity === "keep" ? "clear" : "keep",
              })}
              onDrop={() => onChoice({
                target: "identity",
                action: choices?.identity === "drop" ? "clear" : "drop",
              })}
            />
          ) : null}
        </div>
      </FicheSection>

      <FicheSection label={t("reviewGps")} testId="review-marina-gps">
        <div className="flex items-start justify-between gap-2">
          <p className="font-mono text-[11px] text-slate-400">
            {fiche.lat != null && fiche.lon != null
              ? `${Number(fiche.lat).toFixed(4)}, ${Number(fiche.lon).toFixed(4)}`
              : "—"}
            {fiche.maps_url ? (
              <>
                {" · "}
                <a href={fiche.maps_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                  {t("marinasGoogleMaps")}
                </a>
              </>
            ) : null}
          </p>
          {selectable ? (
            <KeepDrop
              t={t}
              verdict={choices?.gps}
              keepTestId="review-marina-gps-keep"
              dropTestId="review-marina-gps-drop"
              onKeep={() => onChoice({
                target: "gps",
                action: choices?.gps === "keep" ? "clear" : "keep",
              })}
              onDrop={() => onChoice({
                target: "gps",
                action: choices?.gps === "drop" ? "clear" : "drop",
              })}
            />
          ) : null}
        </div>
      </FicheSection>

      <FicheSection
        label={t("reviewUrls")}
        count={urls.length > 1 ? urls.length : null}
        testId="review-marina-urls"
        empty={t("reviewNoUrl")}
      >
        {urls.length ? (
          <ul className="space-y-1.5">
            {urls.map((rec, i) => (
              <li key={rec.url}>
                <UrlKeepRow
                  rec={rec}
                  t={t}
                  selectable={selectable}
                  kept={urlMap[rec.url] === "keep"}
                  keepTestId={`review-marina-url-keep-${rec.key}`}
                  testId={i === 0 ? "review-marina-url" : `review-marina-url-${i}`}
                  onToggle={() => onChoice({
                    target: "url",
                    url: rec.url,
                    action: urlMap[rec.url] === "keep" ? "clear" : "keep",
                  })}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </FicheSection>

      <p className="font-mono text-[10px] uppercase tracking-widest text-slate-300">
        {fiche.enriched ? t("reviewEnriched") : t("reviewNotEnriched")}
        {fiche.enrichment_source ? ` · ${fiche.enrichment_source}` : ""}
      </p>
      {wp.name ? (
        <p className="text-xs text-slate-400">
          {wp.name}{wp.distance_nm != null ? ` · ${Number(wp.distance_nm).toFixed(1)} NM` : ""}
        </p>
      ) : null}

      {FIELD_KEYS.some(([key]) => fieldValues[key]) ? (
      <FicheSection label={t("reviewFields")} testId="review-marina-fields">
        <div className="divide-y divide-line/60 border border-line/60 rounded-sm">
          {FIELD_KEYS.map(([key, label]) => {
            const value = fieldValues[key];
            if (value == null || value === "") return null;
            const verdict = fieldMap[key];
            return (
              <div key={key} className="p-2 flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500">
                    {t(label) === label ? label : t(label)}
                  </p>
                  <p className="text-xs text-slate-300 mt-0.5">{String(value)}</p>
                </div>
                {selectable ? (
                  <KeepDrop
                    t={t}
                    verdict={verdict}
                    keepTestId={`review-marina-field-keep-${key}`}
                    dropTestId={`review-marina-field-drop-${key}`}
                    onKeep={() => onChoice({
                      target: "field", field: key,
                      action: verdict === "keep" ? "clear" : "keep",
                    })}
                    onDrop={() => onChoice({
                      target: "field", field: key,
                      action: verdict === "drop" ? "clear" : "drop",
                    })}
                  />
                ) : null}
              </div>
            );
          })}
        </div>
      </FicheSection>
      ) : null}

      {fiche.resume_avis ? (
        <p className="text-sm text-slate-300 leading-relaxed">{fiche.resume_avis}</p>
      ) : null}
      {tags.name || tags["seamark:name"] ? (
        <p className="font-mono text-[10px] text-slate-500">{t("reviewOsm")} · {tags.name || tags["seamark:name"]}</p>
      ) : null}
    </FicheShell>
  );
}
