import { ExternalLink } from "lucide-react";

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (_) {
    return url;
  }
}

function SourceList({ t, arm, items, total }) {
  const title = arm === "td" ? t("poeSourcesTd") : t("poeSourcesBu");
  const empty = arm === "td" ? t("poeFicheEmptyTd") : t("poeFicheEmptyBu");
  return (
    <div data-testid={`poe-fiche-sources-${arm}`}>
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500 mb-1.5">
        {title}
        {total != null && total > (items || []).length ? (
          <span className="text-slate-600"> ({(items || []).length}/{total})</span>
        ) : null}
      </p>
      {(!items || items.length === 0) ? (
        <p className="text-[11px] text-slate-500 leading-relaxed">{empty}</p>
      ) : (
        <ul className="space-y-1">
          {items.map((s) => (
            <li key={`${arm}-${s.url}`} className="flex items-start gap-1.5 min-w-0">
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer"
                data-testid={`poe-fiche-${arm}-url`}
                className="text-[11px] text-accent hover:text-white truncate font-medium"
                title={s.url}
              >
                {hostOf(s.url)}
              </a>
              {s.from_arm === "both" && (
                <span className="shrink-0 font-mono text-[8px] uppercase tracking-widest text-bio border border-bio/40 px-1 py-px rounded-sm">
                  {t("poeSourceBoth")}
                </span>
              )}
              <a href={s.url} target="_blank" rel="noreferrer" className="shrink-0 text-accent hover:text-white mt-0.5">
                <ExternalLink size={11} />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Fiche de revue d'une ZEE — même geste que ProjectList : nom + URL cliquable.
 * Pas de bouton Générer.
 */
export default function ZoneFiche({ t, fiche, loading, onFlyToPort }) {
  if (loading) {
    return (
      <section className="p-3 border-b border-line" data-testid="poe-zone-fiche-loading">
        <p className="font-mono text-[10px] text-slate-500">{t("poeFicheLoading")}</p>
      </section>
    );
  }
  if (!fiche) return null;
  const ports = fiche.ports || [];
  return (
    <section className="p-3 border-b border-line bg-raised/30 space-y-3" data-testid="poe-zone-fiche">
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
          {t("poeFicheTitle")}
        </p>
        {fiche.confidence_avg != null && (
          <span className="font-mono text-[9px] text-slate-300" data-testid="poe-fiche-score">
            {t("poeConfidenceAvg")} {fiche.confidence_avg}
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3">
        <SourceList t={t} arm="td" items={fiche.sources_td} total={fiche.sources_td_total} />
        <SourceList t={t} arm="bu" items={fiche.sources_bu} total={fiche.sources_bu_total} />
      </div>

      <div data-testid="poe-fiche-ports">
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500 mb-1.5">
          {t("poeFichePorts")} <span className="text-accent">({ports.length})</span>
        </p>
        {ports.length === 0 ? (
          <p className="text-[11px] text-slate-500">{t("poeFicheNoPorts")}</p>
        ) : (
          <div className="divide-y divide-line/60 border border-line/60 rounded-sm max-h-40 overflow-y-auto">
            {ports.map((p) => {
              const href = (p.source_urls || [])[0];
              const canFly = p.lat != null && p.lon != null && onFlyToPort;
              return (
                <div
                  key={p.id || p.name}
                  data-testid={`poe-fiche-port-${p.id || p.name}`}
                  className="p-2 hover:bg-raised/60"
                >
                  <button
                    type="button"
                    disabled={!canFly}
                    onClick={() => canFly && onFlyToPort({
                      id: p.id, lat: p.lat, lon: p.lon, name: p.name,
                    })}
                    className="w-full text-left disabled:cursor-default"
                  >
                    <p className="text-xs font-semibold text-slate-200 leading-snug">{p.name}</p>
                  </button>
                  <div className="flex items-center justify-between mt-1 gap-2">
                    <span className="font-mono text-[10px] text-slate-500 truncate">
                      {p.confidence != null ? `${t("poeConfidence")} ${p.confidence}` : (p.city || "")}
                    </span>
                    {href ? (
                      <a href={href} target="_blank" rel="noreferrer"
                        className="text-accent hover:text-white shrink-0"
                        data-testid="poe-fiche-port-url">
                        <ExternalLink size={11} />
                      </a>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
