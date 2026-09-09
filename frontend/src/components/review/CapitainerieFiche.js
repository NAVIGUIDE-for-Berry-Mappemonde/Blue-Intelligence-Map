export default function CapitainerieFiche({ t, fiche }) {
  if (!fiche) return null;
  return (
    <section className="p-4 space-y-3" data-testid="review-fiche-capitainerie">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
        {t("reviewKindCapitainerie")}
      </p>
      <h3 className="font-heading text-xl text-white leading-snug">{fiche.name || "—"}</h3>
      <p className="font-mono text-[11px] text-slate-400">
        {t("reviewSource")} · {fiche.source || "—"}
        {fiche.osm_id ? ` · OSM ${fiche.osm_id}` : ""}
        {fiche.shom_id ? ` · ${fiche.shom_id}` : ""}
        {fiche.noaa_id ? ` · ${fiche.noaa_id}` : ""}
      </p>
      {fiche.lat != null && fiche.lon != null && (
        <p className="font-mono text-[11px] text-slate-400">
          {t("reviewCoords")} · {Number(fiche.lat).toFixed(4)}, {Number(fiche.lon).toFixed(4)}
          {fiche.maps_url ? (
            <>
              {" · "}
              <a href={fiche.maps_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
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
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-slate-300">
        {fiche.telephone ? <><dt className="text-slate-500">{t("marinasPhone")}</dt><dd>{fiche.telephone}</dd></> : null}
        {fiche.canal_vhf ? <><dt className="text-slate-500">VHF</dt><dd>{fiche.canal_vhf}</dd></> : null}
      </dl>
    </section>
  );
}
