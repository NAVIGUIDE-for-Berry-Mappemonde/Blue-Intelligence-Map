import { ExternalLink } from "lucide-react";

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (_) {
    return url || "";
  }
}

function buUrlOf(fiche) {
  if (typeof fiche?.url_bu === "string") return fiche.url_bu;
  return fiche?.url_bu?.url || "";
}

export default function PoeFiche({ t, fiche }) {
  if (!fiche) return null;
  const href = buUrlOf(fiche);
  const buBoth = fiche?.url_bu?.from_arm === "both";
  return (
    <section className="p-4 space-y-3" data-testid="review-fiche-poe">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
        {t("reviewKindPoe")}
      </p>
      <h3 className="font-heading text-xl text-white leading-snug">{fiche.name || "—"}</h3>
      <p className="font-mono text-[11px] text-slate-400">
        {fiche.zone_name || (fiche.mrgid != null ? `mrgid ${fiche.mrgid}` : "—")}
        {fiche.city ? ` · ${fiche.city}` : ""}
        {fiche.country_iso2 ? ` · ${fiche.country_iso2}` : ""}
      </p>
      {fiche.lat != null && fiche.lon != null && (
        <p className="font-mono text-[11px] text-slate-400">
          {t("reviewCoords")} · {Number(fiche.lat).toFixed(4)}, {Number(fiche.lon).toFixed(4)}
        </p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {fiche.confidence != null && (
          <span className="px-1.5 py-0.5 border border-line rounded-sm font-mono text-[9px] uppercase tracking-widest text-slate-300">
            {t("poeConfidence")} {fiche.confidence}
          </span>
        )}
        {fiche.spatial_kind && (
          <span className="px-1.5 py-0.5 border border-line rounded-sm font-mono text-[9px] uppercase tracking-widest text-slate-300">
            {fiche.spatial_kind}
          </span>
        )}
        {fiche.osm_confidence != null && (
          <span className="px-1.5 py-0.5 border border-line rounded-sm font-mono text-[9px] uppercase tracking-widest text-slate-300">
            {t("reviewOsm")} {fiche.osm_confidence}
          </span>
        )}
      </div>
      <div>
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500 mb-1.5">
          {t("poeSourcesBu")}
        </p>
        {href ? (
          <a href={href} target="_blank" rel="noreferrer"
            data-testid="review-poe-bu-url"
            className="inline-flex items-center gap-1.5 text-sm text-accent hover:text-white">
            {hostOf(href)}
            {buBoth && (
              <span className="font-mono text-[8px] uppercase tracking-widest text-bio border border-bio/40 px-1 py-px rounded-sm">
                {t("poeSourceBoth")}
              </span>
            )}
            <ExternalLink size={12} />
          </a>
        ) : (
          <p className="text-[11px] text-slate-500" data-testid="review-poe-bu-empty">{t("poeFicheEmptyBu")}</p>
        )}
      </div>
    </section>
  );
}
