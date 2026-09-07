import { ExternalLink } from "lucide-react";

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (_) {
    return url || "";
  }
}

export default function ProjectFiche({ t, fiche }) {
  if (!fiche) return null;
  const funders = fiche.funders || [];
  const sites = fiche.sites || [];
  return (
    <section className="p-4 space-y-3" data-testid="review-fiche-project">
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
        {t("reviewKindProject")}
      </p>
      <h3 className="font-heading text-xl text-white leading-snug">{fiche.title || "—"}</h3>
      {fiche.url ? (
        <a href={fiche.url} target="_blank" rel="noreferrer"
          data-testid="review-project-url"
          className="inline-flex items-center gap-1.5 text-sm text-accent hover:text-white">
          {hostOf(fiche.url)} <ExternalLink size={12} />
        </a>
      ) : (
        <p className="text-xs text-slate-500">{t("reviewNoUrl")}</p>
      )}
      {funders.length > 0 && (
        <p className="text-xs text-funder">{t("reviewFunder")} · {funders.join(", ")}</p>
      )}
      {fiche.location && (
        <p className="font-mono text-[11px] text-slate-400">{t("reviewLocation")} · {fiche.location}</p>
      )}
      {fiche.lat != null && fiche.lon != null && (
        <p className="font-mono text-[11px] text-slate-400">
          {t("reviewCoords")} · {Number(fiche.lat).toFixed(4)}, {Number(fiche.lon).toFixed(4)}
        </p>
      )}
      {fiche.verdict && (
        <p className="font-mono text-[10px] uppercase tracking-widest text-slate-300">
          {t("reviewVerdict")} · {fiche.verdict}
        </p>
      )}
      {fiche.description ? (
        <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">{fiche.description}</p>
      ) : null}
      {sites.length > 0 && (
        <ul className="border border-line/60 rounded-sm divide-y divide-line/60">
          {sites.map((s, i) => (
            <li key={s.name || i} className="px-3 py-2 text-xs text-slate-200">
              {s.name || s.location || "site"}
              {s.lat != null && s.lon != null ? (
                <span className="font-mono text-[10px] text-slate-500 ml-2">
                  {Number(s.lat).toFixed(3)}, {Number(s.lon).toFixed(3)}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
