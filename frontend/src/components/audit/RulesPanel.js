import { useMemo, useState } from "react";
import { HelpCircle } from "lucide-react";
import {
  GROUP_ORDER, PROFILE_ORDER, coerceValue, contractRules, inInterval, loc,
  matchingProfile, varyRules,
} from "../../lib/runRules";
import { smallInput } from "./CardShell";

function HelpTip({ text }) {
  if (!text) return null;
  return (
    <span className="relative inline-flex group/help" title={text}>
      <HelpCircle size={11} className="text-slate-500 hover:text-accent cursor-help" />
    </span>
  );
}

function RuleField({ rule, lang, value, onChange, error, disabled }) {
  const title = loc(rule.title, lang);
  const help = loc(rule.help, lang);
  const isBool = typeof rule.value === "boolean";
  const isInt = typeof rule.value === "number" && Number.isInteger(rule.value);
  const iv = rule.interval;
  const step = isInt ? 1 : (iv ? ((iv[1] - iv[0]) <= 2 ? 0.01 : 0.1) : 0.1);
  return (
    <div className={`space-y-1 ${disabled ? "opacity-50" : ""}`} data-testid={`rules-field-${rule.id}`}>
      <div className="flex items-start gap-1.5">
        <label className="flex-1 font-mono text-[10px] text-slate-300 leading-snug">{title}</label>
        <HelpTip text={help} />
      </div>
      {isBool ? (
        <label className="flex items-center gap-2 text-[11px] text-slate-400 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={!!value}
            disabled={disabled}
            onChange={(e) => onChange(e.target.checked)}
            className="accent-current"
          />
          {value ? "oui" : "non"}
        </label>
      ) : iv && typeof rule.value === "number" ? (
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={iv[0]}
            max={iv[1]}
            step={step}
            value={value ?? rule.value}
            disabled={disabled}
            onChange={(e) => onChange(coerceValue(rule, e.target.value))}
            className="flex-1 accent-current"
          />
          <input
            type="number"
            min={iv[0]}
            max={iv[1]}
            step={step}
            value={value ?? ""}
            disabled={disabled}
            onChange={(e) => onChange(coerceValue(rule, e.target.value))}
            className={`${smallInput} w-20`}
          />
          {rule.unit && <span className="font-mono text-[9px] text-slate-500 w-10">{rule.unit}</span>}
        </div>
      ) : (
        <input
          type={typeof rule.value === "number" ? "number" : "text"}
          value={value ?? ""}
          disabled={disabled}
          onChange={(e) => onChange(coerceValue(rule, e.target.value))}
          className={smallInput}
        />
      )}
      {error && <p className="font-mono text-[9px] text-alert">{error}</p>}
      {rule.legacy && (
        <p className="font-mono text-[9px] text-slate-500">{loc(rule.help, lang)}</p>
      )}
    </div>
  );
}

export default function RulesPanel({
  t, lang, mode, catalog, values, setValues, profile, lastProfile,
  onSelectProfile, errors, setErrors, onSaveDefaults,
}) {
  const [contractsOpen, setContractsOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const groupsMeta = catalog?.groups || [];
  const groupLabel = (id) => {
    const g = groupsMeta.find((x) => x.id === id);
    return g ? loc(g, lang) || loc({ fr: g.fr, en: g.en }, lang) : id;
  };

  const byGroup = useMemo(() => {
    const map = {};
    for (const r of varyRules(catalog)) {
      const g = r.group || "budget";
      (map[g] ||= []).push(r);
    }
    return map;
  }, [catalog]);

  const lois = contractRules(catalog);
  const showIdentity = mode === "projects" || mode === "capitaineries";
  const banner = catalog?.identity_banner || {};
  const custom = !profile;
  const titleOf = (id) => {
    const r = (catalog?.rules || []).find((x) => x.id === id);
    return r ? loc(r.title, lang) : "";
  };

  const setField = (rule, raw) => {
    const v = coerceValue(rule, raw);
    if (!inInterval(rule, v)) {
      setErrors((e) => ({
        ...e,
        [rule.id]: t("rulesOutOfInterval")
          .replace("{lo}", String(rule.interval[0]))
          .replace("{hi}", String(rule.interval[1])),
      }));
      return;
    }
    setErrors((e) => {
      const n = { ...e };
      delete n[rule.id];
      return n;
    });
    const next = { ...values, [rule.id]: v };
    setValues(next);
    onSelectProfile(matchingProfile(catalog, next), { keepLast: true });
  };

  const saveDefaults = async () => {
    const body = {};
    for (const r of varyRules(catalog)) {
      if (!r.settings_key || r.legacy) continue;
      body[r.settings_key] = values[r.id];
    }
    if (!Object.keys(body).length) return;
    setSaving(true);
    try {
      await onSaveDefaults(body);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally { setSaving(false); }
  };

  const hasSettingsKeys = varyRules(catalog).some((r) => r.settings_key && !r.legacy);

  return (
    <div className="space-y-4" data-testid="console-rules-panel">
      <div className="flex gap-2" data-testid="rules-profiles">
        {PROFILE_ORDER.map((id) => {
          const spec = catalog?.profiles?.[id] || {};
          const active = profile === id;
          const fallbackLabel = { cdc_default: "rulesProfileDefault", strict: "rulesProfileStrict", recall: "rulesProfileRecall" }[id];
          const fallbackHint = { cdc_default: "rulesProfileDefaultHint", strict: "rulesProfileStrictHint", recall: "rulesProfileRecallHint" }[id];
          return (
            <button
              key={id}
              type="button"
              data-testid={`rules-profile-${id}`}
              onClick={() => onSelectProfile(id)}
              className={`flex-1 px-2 py-2 border rounded-sm text-left ${
                active
                  ? "border-accent bg-accent/15 text-accent"
                  : "border-line text-slate-400 hover:bg-raised"
              }`}
            >
              <p className="font-mono text-[10px] uppercase tracking-[0.14em]">
                {loc(spec.label, lang) || t(fallbackLabel)}
              </p>
              <p className="mt-1 font-mono text-[9px] leading-snug text-slate-500">
                {loc(spec.hint, lang) || t(fallbackHint)}
              </p>
            </button>
          );
        })}
      </div>
      {custom && (
        <span
          data-testid="rules-custom-badge"
          className="inline-block font-mono text-[9px] uppercase tracking-[0.16em] px-2 py-0.5 border border-accent/50 text-accent bg-accent/10 rounded-sm"
        >
          {t("rulesCustom")}
        </span>
      )}

      {showIdentity && (
        <div className="border border-line bg-raised/40 px-3 py-2 space-y-1" data-testid="rules-identity-banner">
          <p className="font-mono text-[10px] text-slate-300">
            {loc(banner.merge_sites, lang)}
            {titleOf("shared.dedup_dist_km") ? ` — ${titleOf("shared.dedup_dist_km")}, 60 % / 90 %` : ""}
          </p>
          <p className="font-mono text-[10px] text-slate-300">
            {loc(banner.overlay_office, lang)}
            {titleOf("capitaineries.merge_km") ? ` — ${titleOf("capitaineries.merge_km")}` : ""}
          </p>
          <p className="font-mono text-[9px] text-slate-500 leading-relaxed">{loc(banner.help, lang)}</p>
        </div>
      )}

      {GROUP_ORDER.filter((g) => g !== "contracts" && (byGroup[g] || []).length).map((gid) => (
        <section key={gid} className="space-y-2.5" data-testid={`rules-group-${gid}`}>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent/80">{groupLabel(gid)}</p>
          {(byGroup[gid] || []).map((rule) => (
            <RuleField
              key={rule.id}
              rule={rule}
              lang={lang}
              value={values[rule.id]}
              error={errors[rule.id]}
              disabled={!!rule.legacy}
              onChange={(v) => setField(rule, v)}
            />
          ))}
        </section>
      ))}

      {lois.length > 0 && (
        <section data-testid="rules-group-contracts">
          <button
            type="button"
            onClick={() => setContractsOpen((o) => !o)}
            className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 hover:text-accent"
          >
            {groupLabel("contracts")} {contractsOpen ? "▾" : "▸"}
          </button>
          {contractsOpen && (
            <ul className="mt-2 space-y-1.5">
              {lois.map((r) => (
                <li key={r.id} className="font-mono text-[10px] text-slate-400 leading-snug">
                  <span className="text-slate-200">{loc(r.title, lang)}</span>
                  {" — "}
                  {loc(r.help, lang)}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {hasSettingsKeys && (
        <button
          type="button"
          data-testid="rules-save-defaults"
          disabled={saving}
          onClick={saveDefaults}
          className="w-full py-1.5 text-xs font-semibold border border-accent/50 text-accent rounded-sm hover:bg-accent/10 disabled:opacity-40"
        >
          {saved ? t("saved") : t("rulesSaveDefaults")}
        </button>
      )}
      <p className="font-mono text-[9px] text-slate-500">
        {t("rulesSaveDefaultsHint")} · {lastProfile}
      </p>
    </div>
  );
}
