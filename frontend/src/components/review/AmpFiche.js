import { LFP_COLORS } from "../map/constants";

export default function AmpFiche({ t, fiche }) {
  if (!fiche) return null;
  const lfp = Number(fiche.lfp) || 0;
  return (
    <section className="p-4 space-y-3" data-testid="review-fiche-amp">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
        {t("reviewKindAmp")}
      </p>
      <h3 className="font-heading text-xl text-white leading-snug">{fiche.name || "—"}</h3>
      <p className="font-mono text-[11px] text-slate-400">
        {fiche.country || "—"}
        {fiche.designation ? ` · ${fiche.designation}` : ""}
        {fiche.site_id ? ` · ${fiche.site_id}` : ""}
      </p>
      <p className="font-mono text-[11px]" style={{ color: LFP_COLORS[lfp] }}>
        LFP {lfp} · {t(`lfp${lfp}`)}
      </p>
      {fiche.managing_authority ? (
        <p className="text-sm text-slate-300">{fiche.managing_authority}</p>
      ) : null}
      <dl className="space-y-2 text-xs">
        <div>
          <dt className="font-mono text-[10px] uppercase tracking-widest text-slate-500">{t("ampManagerUrl")}</dt>
          <dd>
            {fiche.manager_url ? (
              <a href={fiche.manager_url} target="_blank" rel="noreferrer" className="text-slate-300 hover:underline break-all" data-testid="amp-fiche-manager">
                {fiche.manager_url}
              </a>
            ) : <span className="text-slate-600">{t("ampNoManagerUrl")}</span>}
          </dd>
        </div>
        <div>
          <dt className="font-mono text-[10px] uppercase tracking-widest text-[#4ade80]">{t("ampVisitUrl")}</dt>
          <dd>
            {fiche.visit_url ? (
              <a href={fiche.visit_url} target="_blank" rel="noreferrer" className="text-[#4ade80] hover:underline break-all" data-testid="amp-fiche-visit">
                {fiche.visit_url}
              </a>
            ) : <span className="text-slate-600" data-testid="amp-fiche-visit-missing">{t("ampNoVisitUrl")}</span>}
          </dd>
        </div>
      </dl>
      {fiche.purpose ? (
        <p className="text-sm text-slate-300 leading-relaxed">{fiche.purpose}</p>
      ) : null}
    </section>
  );
}
