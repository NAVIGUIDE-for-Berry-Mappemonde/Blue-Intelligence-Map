import { LFP_COLORS } from "../map/constants";
import { FicheSection, FicheShell, UrlKeepRow } from "./choiceUi";

export default function AmpFiche({ t, fiche, choices, onChoice }) {
  if (!fiche) return null;
  const selectable = typeof onChoice === "function";
  const lfp = Number(fiche.lfp) || 0;
  const candidates = fiche.visit_candidates || (
    fiche.visit_url ? [{ url: fiche.visit_url, status: fiche.visit_url_status }] : []
  );
  const visitMap = choices?.visit || {};
  const noVisit = Boolean(choices?.no_visit);
  return (
    <FicheShell
      testId="review-fiche-amp"
      kindLabel={t("reviewKindAmp")}
      title={fiche.name}
      subtitle={[fiche.country, fiche.designation, fiche.site_id].filter(Boolean).join(" · ")}
      extra={(
        <p className="font-mono text-[11px] mt-1" style={{ color: LFP_COLORS[lfp] }}>
          LFP {lfp} · {t(`lfp${lfp}`)}
        </p>
      )}
    >
      {fiche.managing_authority ? (
        <p className="text-sm text-slate-300">{fiche.managing_authority}</p>
      ) : null}

      <FicheSection label={t("ampManagerUrl")} testId="amp-fiche-manager-wrap">
        {fiche.manager_url ? (
          <UrlKeepRow
            rec={{ url: fiche.manager_url }}
            t={t}
            selectable={false}
            testId="amp-fiche-manager"
          />
        ) : (
          <p className="text-[11px] text-slate-500">{t("ampNoManagerUrl")}</p>
        )}
      </FicheSection>

      <FicheSection
        label={t("ampVisitUrl")}
        count={candidates.length > 1 ? candidates.length : null}
        testId="amp-fiche-visit-list"
        empty={t("ampNoVisitUrl")}
      >
        {candidates.length ? (
          <ul className="space-y-1.5">
            {candidates.map((rec, i) => (
              <li key={rec.url}>
                <UrlKeepRow
                  rec={rec}
                  t={t}
                  selectable={selectable && !noVisit}
                  kept={visitMap[rec.url] === "keep"}
                  keepTestId={i === 0 ? "amp-fiche-visit-keep" : `amp-fiche-visit-keep-${i}`}
                  testId={i === 0 ? "amp-fiche-visit" : `amp-fiche-visit-${i}`}
                  badge={rec.same_as_manager ? (
                    <span className="font-mono text-[8px] uppercase tracking-widest text-alert border border-alert/40 px-1 py-px rounded-sm">
                      {t("reviewSameAsManager")}
                    </span>
                  ) : rec.status ? (
                    <span className="font-mono text-[8px] uppercase tracking-widest text-slate-500">
                      {rec.status}
                    </span>
                  ) : null}
                  onToggle={() => onChoice({
                    target: "visit",
                    url: rec.url,
                    action: visitMap[rec.url] === "keep" ? "clear" : "keep",
                  })}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </FicheSection>

      {selectable ? (
        <label className="flex items-center gap-2 text-[11px] text-slate-300">
          <input
            type="checkbox"
            data-testid="amp-fiche-no-visit"
            checked={noVisit}
            onChange={() => onChoice({
              target: "no_visit",
              action: noVisit ? "clear" : "keep",
            })}
            className="accent-accent"
          />
          {t("reviewNoVisit")}
        </label>
      ) : null}

      {fiche.purpose ? (
        <p className="text-sm text-slate-300 leading-relaxed">{fiche.purpose}</p>
      ) : null}
    </FicheShell>
  );
}
