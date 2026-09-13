import { Cloud, Waves, Wind } from "lucide-react";

const COLOR = "#2dd4bf";

const MONTHS = [
  { n: 1, fr: "Janv.", en: "Jan" },
  { n: 2, fr: "Févr.", en: "Feb" },
  { n: 3, fr: "Mars", en: "Mar" },
  { n: 4, fr: "Avr.", en: "Apr" },
  { n: 5, fr: "Mai", en: "May" },
  { n: 6, fr: "Juin", en: "Jun" },
  { n: 7, fr: "Juil.", en: "Jul" },
  { n: 8, fr: "Août", en: "Aug" },
  { n: 9, fr: "Sept.", en: "Sep" },
  { n: 10, fr: "Oct.", en: "Oct" },
  { n: 11, fr: "Nov.", en: "Nov" },
  { n: 12, fr: "Déc.", en: "Dec" },
];

const FILTERS = [
  { id: "wind", labelKey: "climoFilterWind" },
  { id: "wave", labelKey: "climoFilterWave" },
  { id: "current", labelKey: "climoFilterCurrent" },
  { id: "cyclones", labelKey: "climoFilterCyclones" },
];

/**
 * ClimatologyPanel — curseur janvier–décembre + filtres Vent / Houle /
 * Courant / Cyclones. Modèle : SciencePanel (Sextant / Argo).
 */
export default function ClimatologyPanel({
  t, lang = "fr",
  month = 1, onMonth,
  filters, onToggleFilter,
  waveStat = "mean", onWaveStat,
  meta, point,
}) {
  const monthLabel = MONTHS[month - 1];
  const label = lang === "en" ? monthLabel?.en : monthLabel?.fr;
  const snaps = meta?.snapshot || {};

  return (
    <aside className="w-[360px] shrink-0 flex flex-col border-r border-line bg-surface" data-testid="climatology-panel">
      <div className="p-4 border-b border-line">
        <div className="flex items-center gap-2 mb-1">
          <Wind size={18} className="text-accent" />
          <h2 className="font-heading font-bold text-white text-base">{t("modeClimatologyFull")}</h2>
        </div>
        <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-3">
          {t("climoSubtitle")}
        </p>

        <label className="block font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-1" htmlFor="climo-month">
          {t("climoMonth")} · {label}
        </label>
        <input
          id="climo-month"
          data-testid="climatology-month"
          type="range"
          min={1}
          max={12}
          step={1}
          value={month}
          onChange={(e) => onMonth && onMonth(Number(e.target.value))}
          className="w-full accent-teal-400 mb-3"
        />
        <div className="flex justify-between font-mono text-[8px] text-slate-600 mb-3">
          <span>J</span><span>F</span><span>M</span><span>A</span><span>M</span><span>J</span>
          <span>J</span><span>A</span><span>S</span><span>O</span><span>N</span><span>D</span>
        </div>

        <div className="flex flex-wrap gap-1 mb-2" data-testid="climatology-filters">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              data-testid={`climatology-filter-${f.id}`}
              onClick={() => onToggleFilter && onToggleFilter(f.id, !(filters && filters[f.id]))}
              className={`px-1.5 py-1 font-mono text-[9px] uppercase tracking-wide border rounded-sm transition-colors ${
                filters && filters[f.id]
                  ? "border-accent/60 bg-accent/15 text-accent"
                  : "border-line text-slate-500 hover:text-slate-300 hover:bg-raised"
              }`}
            >
              {t(f.labelKey)}
            </button>
          ))}
        </div>

        {filters?.wave && (
          <div className="flex flex-wrap gap-1 mb-3" data-testid="climatology-wave-stat">
            {(snaps.wave_stat === "p50_p90" ? ["p50", "p90"] : ["mean"]).map((s) => (
              <button
                key={s}
                type="button"
                data-testid={`climatology-wave-${s}`}
                onClick={() => onWaveStat && onWaveStat(s)}
                className={`px-1.5 py-1 font-mono text-[9px] uppercase tracking-wide border rounded-sm ${
                  waveStat === s
                    ? "border-accent/60 bg-accent/15 text-accent"
                    : "border-line text-slate-500 hover:text-slate-300"
                }`}
              >
                {s === "p50" ? t("climoWaveP50") : s === "p90" ? t("climoWaveP90") : t("climoWaveMean")}
              </button>
            ))}
          </div>
        )}

        <div className="mb-2" data-testid="climatology-legend">
          <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-1.5">{t("legend")}</p>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Wind size={11} className="text-accent shrink-0" />
              <span className="text-[11px] text-slate-300">{t("climoLegendWind")}</span>
            </div>
            <div className="flex items-center gap-2">
              <Waves size={11} className="text-accent shrink-0" />
              <span className="text-[11px] text-slate-300">{t("climoLegendWave")}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-3 h-0.5 shrink-0 bg-accent" />
              <span className="text-[11px] text-slate-300">{t("climoLegendCurrent")}</span>
            </div>
            <div className="flex items-center gap-2">
              <Cloud size={11} className="text-accent shrink-0" />
              <span className="text-[11px] text-slate-300">{t("climoLegendCyclones")}</span>
            </div>
          </div>
        </div>

        <div className="font-mono text-[9px] text-slate-500 space-y-0.5 mb-2" data-testid="climatology-snapshot-status">
          {["wind", "wave", "current", "cyclones"].map((k) => (
            <div key={k}>
              {t(`climoFilter${k[0].toUpperCase()}${k.slice(1)}`)}
              {" · "}
              {snaps[k] ? t("climoSnapshotOn") : t("climoSnapshotOff")}
            </div>
          ))}
        </div>
        <p className="font-mono text-[9px] text-slate-500 leading-relaxed">{t("climoHint")}</p>
      </div>

      <div className="flex-1 overflow-y-auto p-4" data-testid="climatology-point">
        {point ? (
          <PointCard t={t} point={point} />
        ) : (
          <p className="text-xs text-slate-500 leading-relaxed">{t("climoClickHint")}</p>
        )}
      </div>

      <div className="px-4 py-2 border-t border-line space-y-1">
        <p className="font-mono text-[10px] text-amber-200/90 leading-relaxed" data-testid="climatology-disclaimer">
          {t("climoDisclaimer")}
        </p>
        <p className="font-mono text-[10px] text-slate-300 leading-relaxed" data-testid="climatology-attribution">
          {t("climoAttribution")}
        </p>
      </div>
    </aside>
  );
}

function PointCard({ t, point }) {
  const land = point.coordinates?.cell_selection === "land";
  const w = point.wind_atlas;
  const wave = point.wave;
  const cur = point.current;
  const cyc = point.cyclone;
  return (
    <div className="space-y-3" data-testid="climatology-point-card">
      <p className="font-mono text-[10px] text-slate-400">
        {Number(point.coordinates?.latitude).toFixed(2)}°, {Number(point.coordinates?.longitude).toFixed(2)}°
        {" · "}{land ? t("climoOnLand") : t("climoAtSea")}
        {" · "}kind {point.kind}
      </p>
      {land && (
        <p className="text-xs text-slate-400">{t("climoLandNull")}</p>
      )}
      <Block title={t("climoFilterWind")} empty={!w} emptyLabel={t("climoNoValue")}>
        {w && (
          <>
            <Row k="stat" v={w.stat || (w.most_likely ? "rose" : "average")} />
            {w.most_likely && (
              <Row k="MOST_LIKELY" v={`${w.most_likely.speed_knots} kn / ${w.most_likely.dir_deg}°`} />
            )}
            {w.vector_mean && (
              <Row k="AVERAGE" v={`${w.vector_mean.speed_knots} kn / ${w.vector_mean.dir_deg}°`} />
            )}
            {w.calm_pct != null && (
              <Row k="calm / gale" v={`${w.calm_pct}% / ${w.gale_pct}%`} />
            )}
            {w.sample_count != null && <Row k="n" v={String(w.sample_count)} />}
          </>
        )}
      </Block>
      <Block title={t("climoFilterWave")} empty={!wave} emptyLabel={t("climoNoValue")}>
        {wave && (
          <>
            <Row k="stat" v={wave.stat} />
            {wave.hs_p50_m != null && <Row k="P50" v={`${wave.hs_p50_m} m`} />}
            {wave.hs_p90_m != null && <Row k="P90" v={`${wave.hs_p90_m} m`} />}
            {wave.hs_mean_m != null && <Row k="mean" v={`${wave.hs_mean_m} m`} />}
            {wave.period_s != null && <Row k="T" v={`${wave.period_s} s`} />}
          </>
        )}
      </Block>
      <Block title={t("climoFilterCurrent")} empty={!cur} emptyLabel={t("climoNoValue")}>
        {cur && (
          <>
            <Row k="kn" v={String(cur.speed_knots)} />
            <Row k="to" v={`${cur.direction_to_deg}°`} />
            {cur.below_threshold && <Row k="flag" v="below_threshold" />}
          </>
        )}
      </Block>
      <Block title={t("climoFilterCyclones")} empty={false}>
        <Row k="tracks" v={String(cyc?.tracks_in_month ?? 0)} />
        {cyc?.crossings_if_leg && (
          <Row k="crossings" v={String(cyc.crossings_if_leg.count)} />
        )}
      </Block>
      <p className="font-mono text-[9px] text-slate-500 leading-relaxed">
        {point.provenance?.wind}
      </p>
    </div>
  );
}

function Block({ title, empty, emptyLabel, children }) {
  return (
    <div>
      <p className="font-mono text-[9px] uppercase tracking-widest text-slate-500 mb-1">{title}</p>
      {empty ? <p className="text-[11px] text-slate-500">{emptyLabel}</p> : <div className="space-y-0.5">{children}</div>}
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex justify-between gap-2 text-[11px]">
      <span className="font-mono text-slate-500">{k}</span>
      <span className="text-slate-200">{v}</span>
    </div>
  );
}
