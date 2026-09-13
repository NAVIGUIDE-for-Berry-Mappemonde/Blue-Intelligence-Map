/**
 * Console — mode Climatologie. Pas de moisson / Gold : statut des snapshots.
 */
export default function ClimatologyCard({ t }) {
  return (
    <div className="space-y-3" data-testid="climatology-launch">
      <p className="font-mono text-[11px] text-slate-300 leading-relaxed">
        {t("auditClimatologyHint")}
      </p>
      <p className="font-mono text-[10px] text-slate-500 leading-relaxed">
        kind: climatology · CMEMS + IBTrACS · {t("climoDisclaimer")}
      </p>
    </div>
  );
}
