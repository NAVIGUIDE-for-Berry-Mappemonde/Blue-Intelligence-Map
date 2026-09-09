import { FicheSection, FicheShell, KeepDrop, UrlKeepRow } from "./choiceUi";

export default function CapitainerieFiche({ t, fiche, choices, onChoice }) {
  if (!fiche) return null;
  const selectable = typeof onChoice === "function";
  const sources = fiche.sources || [];
  const fieldMap = choices?.fields || {};
  const urlMap = choices?.urls || {};
  const urls = fiche.website ? [fiche.website] : [];
  const fields = [
    ["telephone", fiche.telephone, t("marinasPhone")],
    ["canal_vhf", fiche.canal_vhf, "VHF"],
  ].filter((row) => row[1]);
  return (
    <FicheShell
      testId="review-fiche-capitainerie"
      kindLabel={t("reviewKindCapitainerie")}
      title={fiche.name}
      subtitle={[
        fiche.source,
        fiche.osm_id ? `OSM ${fiche.osm_id}` : null,
        fiche.shom_id,
        fiche.noaa_id,
      ].filter(Boolean).join(" · ")}
    >
      {sources.length ? (
        <p className="font-mono text-[10px] text-slate-500" data-testid="review-capitainerie-sources">
          {t("reviewSource")} · {sources.join(" · ")}
        </p>
      ) : null}

      <FicheSection label={t("reviewIdentity")} testId="review-capitainerie-identity">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs text-slate-300 leading-snug">{t("reviewBureauHint")}</p>
          {selectable ? (
            <KeepDrop
              t={t}
              verdict={choices?.identity}
              keepTestId="review-capitainerie-identity-keep"
              dropTestId="review-capitainerie-identity-drop"
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

      <FicheSection label={t("reviewGps")} testId="review-capitainerie-gps">
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
              keepTestId="review-capitainerie-gps-keep"
              dropTestId="review-capitainerie-gps-drop"
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

      {(fiche.shom_id || fiche.noaa_id) ? (
      <FicheSection label={t("reviewOverlay")} testId="review-capitainerie-overlay">
        <div className="flex items-start justify-between gap-2">
          <p className="text-xs text-slate-300 leading-snug">{t("reviewOverlayHint")}</p>
          {selectable ? (
            <KeepDrop
              t={t}
              verdict={choices?.overlay}
              keepTestId="review-capitainerie-overlay-keep"
              dropTestId="review-capitainerie-overlay-drop"
              onKeep={() => onChoice({
                target: "overlay",
                action: choices?.overlay === "keep" ? "clear" : "keep",
              })}
              onDrop={() => onChoice({
                target: "overlay",
                action: choices?.overlay === "drop" ? "clear" : "drop",
              })}
            />
          ) : null}
        </div>
      </FicheSection>
      ) : null}

      <FicheSection
        label={t("reviewUrls")}
        testId="review-capitainerie-urls"
        empty={t("reviewNoUrl")}
      >
        {urls.length ? (
          <ul className="space-y-1.5">
            {urls.map((href) => (
              <li key={href}>
                <UrlKeepRow
                  rec={{ url: href }}
                  t={t}
                  selectable={selectable}
                  kept={urlMap[href] === "keep"}
                  keepTestId="review-capitainerie-url-keep"
                  testId="review-capitainerie-url"
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

      {fields.length ? (
        <FicheSection label={t("reviewFields")} testId="review-capitainerie-fields">
          <div className="divide-y divide-line/60 border border-line/60 rounded-sm">
            {fields.map(([key, value, label]) => {
              const verdict = fieldMap[key];
              return (
                <div key={key} className="p-2 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500">{label}</p>
                    <p className="text-xs text-slate-300 mt-0.5">{value}</p>
                  </div>
                  {selectable ? (
                    <KeepDrop
                      t={t}
                      verdict={verdict}
                      keepTestId={`review-capitainerie-field-keep-${key}`}
                      dropTestId={`review-capitainerie-field-drop-${key}`}
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
    </FicheShell>
  );
}
