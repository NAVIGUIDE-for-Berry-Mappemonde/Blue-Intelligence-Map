export default function MarinaFiche({ t, fiche }) {
  if (!fiche) return null;
  const tags = fiche.tags || {};
  const wp = fiche.nearest_waypoint || {};
  const services = Array.isArray(fiche.services_disponibles)
    ? fiche.services_disponibles.join(", ")
    : (fiche.services_disponibles || "");
  return (
    <section className="p-4 space-y-3" data-testid="review-fiche-marina">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
        {t("reviewKindMarina")}
      </p>
      <h3 className="font-heading text-xl text-white leading-snug">{fiche.name || "—"}</h3>
      <p className="font-mono text-[11px] text-slate-400">
        {t("reviewSource")} · {fiche.source || "—"}
        {fiche.priority != null ? ` · P${fiche.priority}` : ""}
      </p>
      {fiche.lat != null && fiche.lon != null && (
        <p className="font-mono text-[11px] text-slate-400">
          {t("reviewCoords")} · {Number(fiche.lat).toFixed(4)}, {Number(fiche.lon).toFixed(4)}
          {fiche.maps_url ? (
            <>
              {" · "}
              <a href={fiche.maps_url} target="_blank" rel="noreferrer" className="text-alert hover:underline">
                {t("marinasGoogleMaps")}
              </a>
            </>
          ) : null}
        </p>
      )}
      {fiche.website ? (
        <p className="font-mono text-[11px] text-slate-400 truncate">
          <a href={fiche.website} target="_blank" rel="noreferrer" className="text-bio hover:underline">
            {fiche.website.replace(/^https?:\/\//, "")}
          </a>
        </p>
      ) : null}
      <p className="font-mono text-[10px] uppercase tracking-widest text-slate-300">
        {fiche.enriched ? t("reviewEnriched") : t("reviewNotEnriched")}
        {fiche.enrichment_source ? ` · ${fiche.enrichment_source}` : ""}
      </p>
      {wp.name && (
        <p className="text-xs text-slate-400">
          {wp.name}{wp.distance_nm != null ? ` · ${Number(wp.distance_nm).toFixed(1)} NM` : ""}
        </p>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-300">
        {fiche.canal_vhf ? <><dt className="text-slate-500">VHF</dt><dd>{fiche.canal_vhf}</dd></> : null}
        {fiche.places_visiteurs != null ? <><dt className="text-slate-500">Visiteurs</dt><dd>{fiche.places_visiteurs}</dd></> : null}
        {fiche.tirant_eau_max_metres != null ? <><dt className="text-slate-500">Tirant d'eau</dt><dd>{fiche.tirant_eau_max_metres} m</dd></> : null}
        {fiche.score_protection_meteo != null ? <><dt className="text-slate-500">Protection</dt><dd>{fiche.score_protection_meteo}</dd></> : null}
        {fiche.telephone_capitainerie ? <><dt className="text-slate-500">Capitainerie</dt><dd>{fiche.telephone_capitainerie}</dd></> : null}
        {services ? <><dt className="text-slate-500">Services</dt><dd className="col-span-1">{services}</dd></> : null}
      </dl>
      {fiche.resume_avis ? (
        <p className="text-sm text-slate-300 leading-relaxed">{fiche.resume_avis}</p>
      ) : null}
      {tags.name || tags["seamark:name"] ? (
        <p className="font-mono text-[10px] text-slate-500">{t("reviewOsm")} · {tags.name || tags["seamark:name"]}</p>
      ) : null}
    </section>
  );
}
