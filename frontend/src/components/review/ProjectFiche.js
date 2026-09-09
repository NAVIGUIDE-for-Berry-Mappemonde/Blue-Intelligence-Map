import { FicheSection, FicheShell, KeepDrop, UrlKeepRow } from "./choiceUi";

export default function ProjectFiche({ t, fiche, choices, onChoice }) {
  if (!fiche) return null;
  const selectable = typeof onChoice === "function";
  const funders = fiche.funders || [];
  const urls = (fiche.urls && fiche.urls.length) ? fiche.urls : (fiche.url ? [fiche.url] : []);
  const sites = fiche.sites || [];
  const urlMap = choices?.urls || {};
  const siteMap = choices?.sites || {};
  const gpsEdit = choices?.gps_edit || {};
  const verdicts = fiche.verdicts || [];
  return (
    <FicheShell
      testId="review-fiche-project"
      kindLabel={t("reviewKindProject")}
      title={fiche.title}
      subtitle={funders.length ? `${t("reviewFunder")} · ${funders.join(", ")}` : null}
      extra={fiche.fiche_scope === "union" ? (
        <p className="font-mono text-[10px] text-slate-500 mt-1" data-testid="review-project-union-hint">
          {t("reviewUnionHint")}
        </p>
      ) : null}
    >
      <FicheSection
        label={t("reviewUrls")}
        count={urls.length > 1 ? urls.length : null}
        testId="review-project-urls"
        empty={t("reviewNoUrl")}
      >
        {urls.length ? (
          <ul className="space-y-1.5">
            {urls.map((href, i) => (
              <li key={href}>
                <UrlKeepRow
                  rec={{ url: href }}
                  t={t}
                  selectable={selectable}
                  kept={urlMap[href] === "keep"}
                  keepTestId={i === 0 ? "review-project-url-keep" : `review-project-url-keep-${i}`}
                  testId={i === 0 ? "review-project-url" : `review-project-url-${i}`}
                  onToggle={() => onChoice({
                    target: "url",
                    url: href,
                    action: urlMap[href] === "keep" ? "clear" : "keep",
                  })}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </FicheSection>

      {fiche.location ? (
        <p className="font-mono text-[11px] text-slate-400">{t("reviewLocation")} · {fiche.location}</p>
      ) : null}
      {verdicts.length ? (
        <p className="font-mono text-[10px] uppercase tracking-widest text-slate-300" data-testid="review-project-verdicts">
          {t("reviewVerdict")} · {verdicts.join(" · ")}
        </p>
      ) : fiche.verdict ? (
        <p className="font-mono text-[10px] uppercase tracking-widest text-slate-300">
          {t("reviewVerdict")} · {fiche.verdict}
        </p>
      ) : null}
      {fiche.description ? (
        <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{fiche.description}</p>
      ) : null}

      <FicheSection
        label={t("reviewSites")}
        count={sites.length}
        testId="review-project-sites"
        empty={t("reviewNoSites")}
      >
        {sites.length ? (
          <div className="divide-y divide-line/60 border border-line/60 rounded-sm max-h-[45vh] overflow-y-auto">
            {sites.map((s) => {
              const sid = s.site_id || s.id || s.name;
              const verdict = siteMap[sid];
              const edited = gpsEdit[sid];
              const lat = edited?.lat ?? s.lat;
              const lon = edited?.lon ?? s.lon;
              return (
                <div key={sid} className="p-2 hover:bg-raised/60" data-testid={`review-project-site-${sid}`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold text-slate-200 leading-snug">{s.name || s.location || "site"}</p>
                      <p className="font-mono text-[10px] text-slate-500 mt-1">
                        {lat != null && lon != null
                          ? `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}`
                          : "—"}
                        {s.geo_source ? ` · ${s.geo_source}` : ""}
                        {s.site_ok ? ` · ${t("reviewSiteOk")}` : ` · ${t("reviewSiteBad")}`}
                      </p>
                    </div>
                    {selectable ? (
                      <KeepDrop
                        t={t}
                        verdict={verdict}
                        keepTestId={`review-project-site-keep-${sid}`}
                        dropTestId={`review-project-site-drop-${sid}`}
                        onKeep={() => onChoice({
                          target: "site", site_id: sid,
                          action: verdict === "keep" ? "clear" : "keep",
                        })}
                        onDrop={() => onChoice({
                          target: "site", site_id: sid,
                          action: verdict === "drop" ? "clear" : "drop",
                        })}
                      />
                    ) : null}
                  </div>
                  {selectable ? (
                    <div className="flex items-center gap-2 mt-2">
                      <input
                        type="number"
                        step="0.0001"
                        data-testid={`review-project-site-lat-${sid}`}
                        defaultValue={lat ?? ""}
                        placeholder="lat"
                        className="w-28 bg-raised border border-line rounded-sm px-1.5 py-0.5 font-mono text-[10px] text-slate-200"
                        onBlur={(e) => {
                          const nextLat = parseFloat(e.target.value);
                          const nextLon = Number(lon);
                          if (Number.isFinite(nextLat) && Number.isFinite(nextLon)) {
                            onChoice({
                              target: "gps_edit", site_id: sid, action: "keep",
                              lat: nextLat, lon: nextLon,
                            });
                          }
                        }}
                      />
                      <input
                        type="number"
                        step="0.0001"
                        data-testid={`review-project-site-lon-${sid}`}
                        defaultValue={lon ?? ""}
                        placeholder="lon"
                        className="w-28 bg-raised border border-line rounded-sm px-1.5 py-0.5 font-mono text-[10px] text-slate-200"
                        onBlur={(e) => {
                          const nextLon = parseFloat(e.target.value);
                          if (Number.isFinite(Number(lat)) && Number.isFinite(nextLon)) {
                            onChoice({
                              target: "gps_edit", site_id: sid, action: "keep",
                              lat: Number(lat), lon: nextLon,
                            });
                          }
                        }}
                      />
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : null}
      </FicheSection>
    </FicheShell>
  );
}
