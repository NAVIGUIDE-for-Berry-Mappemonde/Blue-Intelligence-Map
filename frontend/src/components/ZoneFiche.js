import { ExternalLink } from "lucide-react";
import { zoneDisplayName, zoneSubtitle } from "./map/zoneLabel";

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (_) {
    return url;
  }
}

function tdUrlOf(fiche) {
  return fiche?.url_td?.url || (fiche?.sources_td || [])[0]?.url || "";
}

function buUrlOf(port) {
  if (typeof port?.url_bu === "string") return port.url_bu;
  return port?.url_bu?.url || (port?.source_urls || [])[0] || "";
}

/**
 * Fiche de revue d'un polygone VLIZ — même geste que ProjectList :
 * une URL TD (liste officielle) + chaque PoE avec une URL BU.
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
  const td = tdUrlOf(fiche);
  const tdBoth = fiche?.url_td?.from_arm === "both" || (fiche?.sources_td || [])[0]?.from_arm === "both";
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
      <div>
        <p className="font-heading text-sm text-white leading-snug" data-testid="poe-fiche-zone-label">
          {zoneDisplayName(fiche, t)}
        </p>
        {zoneSubtitle(fiche) ? (
          <p className="font-mono text-[10px] text-slate-500 mt-0.5">{zoneSubtitle(fiche)}</p>
        ) : null}
      </div>

      <div data-testid="poe-fiche-sources-td">
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500 mb-1.5">
          {t("poeSourcesTd")}
        </p>
        {td ? (
          <div className="flex items-center justify-between gap-2 min-w-0">
            <a
              href={td}
              target="_blank"
              rel="noreferrer"
              data-testid="poe-fiche-td-url"
              className="text-[11px] text-accent hover:text-white truncate font-medium"
              title={td}
            >
              {hostOf(td)}
            </a>
            <div className="flex items-center gap-1 shrink-0">
              {tdBoth && (
                <span className="font-mono text-[8px] uppercase tracking-widest text-bio border border-bio/40 px-1 py-px rounded-sm">
                  {t("poeSourceBoth")}
                </span>
              )}
              <a href={td} target="_blank" rel="noreferrer" className="text-accent hover:text-white">
                <ExternalLink size={11} />
              </a>
            </div>
          </div>
        ) : (
          <p className="text-[11px] text-slate-500 leading-relaxed">{t("poeFicheEmptyTd")}</p>
        )}
      </div>

      <div data-testid="poe-fiche-ports">
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500 mb-1.5">
          {t("poeFichePorts")} <span className="text-accent">({ports.length})</span>
        </p>
        {ports.length === 0 ? (
          <p className="text-[11px] text-slate-500">{t("poeFicheNoPorts")}</p>
        ) : (
          <div className="divide-y divide-line/60 border border-line/60 rounded-sm max-h-56 overflow-y-auto">
            {ports.map((p) => {
              const href = buUrlOf(p);
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
                        data-testid="poe-fiche-port-bu"
                        title={href}>
                        <ExternalLink size={11} />
                      </a>
                    ) : (
                      <span className="font-mono text-[9px] text-slate-600" data-testid="poe-fiche-port-bu-empty">—</span>
                    )}
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
