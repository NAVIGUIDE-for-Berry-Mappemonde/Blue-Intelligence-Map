import { Wind } from "lucide-react";

const COLOR = "#fb923c";

/**
 * ClimatologyPanel — stub C0 du 7ᵉ mode. C4 remplacera ce placeholder
 * par le curseur de mois et les filtres Vent / Houle / Courant / Cyclones.
 */
export default function ClimatologyPanel({ t }) {
  return (
    <aside className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface" data-testid="climatology-panel">
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-2 mb-1">
          <Wind size={18} style={{ color: COLOR }} />
          <h2 className="font-heading font-bold text-white text-base">{t("modeClimatology")}</h2>
        </div>
        <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-3">
          {t("climatologySubtitle")}
        </p>
        <div
          data-testid="climatology-disclaimer"
          className="text-[11px] leading-relaxed px-2.5 py-2 rounded-sm border border-[#fb923c]/40 bg-[#fb923c]/10 text-[#fb923c]"
        >
          ⚠️ {t("climatologyDisclaimer")}
        </div>
      </div>
    </aside>
  );
}
