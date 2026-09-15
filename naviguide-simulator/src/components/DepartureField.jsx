import { useLang } from "../i18n/LangContext.jsx";
import { parseDepartureUtc, splitDepartureUtc } from "../engine/voyageClock.js";

export function DepartureField({ t0, startAt, onT0, onStartAt }) {
  const { t, lang } = useLang();
  const { date, time } = splitDepartureUtc(t0);

  const setDate = (nextDate) => onT0?.(parseDepartureUtc(nextDate, time));
  const setTime = (nextTime) => onT0?.(parseDepartureUtc(date, nextTime));

  return (
    <div className="rounded-lg border border-white/10 bg-slate-800/50 px-2 py-1 space-y-1">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-slate-400">
        {t("departureTitle")}
      </div>
      <div className="grid grid-cols-2 gap-1">
        <label className="block">
          <span className="text-[8px] text-slate-500">{t("departureDate")}</span>
          <input
            type="date"
            lang={lang}
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="mt-0.5 w-full bg-slate-900/80 border border-white/10 rounded px-1.5 py-0.5 text-[10px] text-white"
          />
        </label>
        <label className="block">
          <span className="text-[8px] text-slate-500">{t("departureTimeUtc")}</span>
          <input
            type="time"
            lang={lang}
            value={time}
            onChange={(e) => setTime(e.target.value)}
            className="mt-0.5 w-full bg-slate-900/80 border border-white/10 rounded px-1.5 py-0.5 text-[10px] text-white"
          />
        </label>
      </div>
      <fieldset className="flex flex-wrap gap-x-3 gap-y-0.5">
        <legend className="text-[8px] text-slate-500">{t("departureStartAt")}</legend>
        <label className="flex items-center gap-1 text-[10px] text-white/80">
          <input
            type="radio"
            name="voyage-start-at"
            checked={startAt === "la-rochelle"}
            onChange={() => onStartAt?.("la-rochelle")}
          />
          {t("departureLaRochelle")}
        </label>
        <label className="flex items-center gap-1 text-[10px] text-white/80">
          <input
            type="radio"
            name="voyage-start-at"
            checked={startAt === "saint-maur"}
            onChange={() => onStartAt?.("saint-maur")}
          />
          {t("departureSaintMaur")}
        </label>
      </fieldset>
    </div>
  );
}
