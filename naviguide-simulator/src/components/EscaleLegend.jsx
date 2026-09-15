import { useLang } from "../i18n/LangContext.jsx";
import { formatCivilDate } from "../engine/voyageClock.js";

function markAt(m) {
  return Number(m.filmNm ?? m.nm) || 0;
}

export function EscaleLegend({ marks, filmNm, onSeek }) {
  const { t, lang } = useLang();
  const list = (marks || []).filter((m) => m?.name);
  if (!list.length) return null;
  const x = Number(filmNm) || 0;
  let current = 0;
  for (let i = 0; i < list.length; i++) {
    if (markAt(list[i]) <= x + 0.4) current = i;
  }

  return (
    <div className="rounded-lg border border-white/10 bg-slate-800/50 overflow-hidden">
      <div className="px-2 py-1 text-[9px] font-semibold uppercase tracking-wider text-slate-400">
        {t("escalesList")}
      </div>
      <ul className="max-h-36 overflow-y-auto sidebar-scroll">
        {list.map((m, i) => {
          const at = markAt(m);
          const active = i === current;
          return (
            <li key={`${m.name}-${at}`}>
              <button
                type="button"
                onClick={() => onSeek?.(at, { jump: true })}
                title={t("escalesJump", { name: m.name })}
                className={`w-full text-left px-2 py-1 text-[11px] border-t border-white/5 ${
                  active
                    ? "bg-cyan-700/40 text-white"
                    : "text-white/70 hover:bg-white/5 hover:text-white"
                }`}
              >
                <span className="font-medium leading-tight block truncate">{m.name}</span>
                <span className="text-[9px] text-white/40">
                  {Math.round(Number(m.nm) || 0).toLocaleString()} nm
                  {m.iso ? ` · ${formatCivilDate(m.iso, lang)}` : ""}
                  {m.holdHours > 0 ? ` · ${t("escalesQuay", { days: Math.round(m.holdHours / 24) })}` : ""}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
