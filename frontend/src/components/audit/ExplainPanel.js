/**
 * Onglet Explication — français courant, par mode.
 */
export default function ExplainPanel({ t, mode }) {
  const key = {
    projects: "explainProjects",
    marinas: "explainMarinas",
    capitaineries: "explainOffices",
    formalities: "explainFormalities",
    amp: "explainAmp",
    science: "explainScience",
    climatology: "explainClimatology",
  }[mode] || "explainProjects";

  return (
    <div className="space-y-3 text-[12px] text-slate-300 leading-relaxed" data-testid="console-explain-panel">
      <p className="font-heading font-bold text-sm text-white">{t("consoleTabExplain")}</p>
      <p>{t(key)}</p>
      <p className="font-mono text-[10px] text-slate-500">{t("explainShared")}</p>
    </div>
  );
}
