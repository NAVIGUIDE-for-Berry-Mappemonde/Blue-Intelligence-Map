/** Catalogue Console — libellés depuis GET /api/run-rules, pas i18n. */

export const GROUP_ORDER = [
  "identity", "space", "qualification", "geocode", "reading", "budget", "contracts",
];

export const PROFILE_ORDER = ["cdc_default", "strict", "recall"];

export const RUNS_API = {
  projects: { list: "/projects/runs", detail: (id) => `/projects/runs/${id}` },
  marinas: { list: "/marinas/runs", detail: (id) => `/marinas/runs/${id}` },
  capitaineries: { list: "/capitaineries/runs", detail: (id) => `/capitaineries/runs/${id}` },
  formalities: { list: "/poe/runs", detail: (id) => `/poe/runs/${id}` },
  amp: { list: "/amp/runs", detail: (id) => `/amp/runs/${id}` },
};

export function loc(obj, lang) {
  if (!obj) return "";
  if (typeof obj === "string") return obj;
  return obj[lang] || obj.fr || obj.en || "";
}

export function coerceValue(rule, raw) {
  if (typeof rule.value === "boolean") {
    if (typeof raw === "boolean") return raw;
    if (raw === "true" || raw === "1" || raw === true) return true;
    return false;
  }
  if (typeof rule.value === "number" && Number.isInteger(rule.value) && !String(rule.value).includes(".")) {
    const n = parseInt(raw, 10);
    return Number.isFinite(n) ? n : rule.value;
  }
  if (typeof rule.value === "number") {
    const n = parseFloat(raw);
    return Number.isFinite(n) ? n : rule.value;
  }
  return raw;
}

export function inInterval(rule, value) {
  const iv = rule.interval;
  if (!iv || value == null || typeof value === "boolean") return true;
  const n = Number(value);
  if (!Number.isFinite(n)) return false;
  return n >= iv[0] && n <= iv[1];
}

export function sameValue(a, b) {
  if (typeof a === "boolean" || typeof b === "boolean") return Boolean(a) === Boolean(b);
  if (typeof a === "number" || typeof b === "number") {
    return Number(a) === Number(b);
  }
  return a === b;
}

export function varyRules(catalog) {
  return (catalog?.rules || []).filter((r) => r.vary && r.kind !== "loi");
}

export function contractRules(catalog) {
  return (catalog?.rules || []).filter((r) => r.kind === "loi" || r.group === "contracts");
}

export function profileBase(catalog, profile) {
  const out = {};
  const ov = catalog?.profiles?.[profile]?.overrides || {};
  for (const r of catalog?.rules || []) {
    out[r.id] = ov[r.id] !== undefined ? ov[r.id] : r.value;
  }
  return out;
}

export function backendResolved(catalog, profile, settings) {
  const ov = catalog?.profiles?.[profile]?.overrides || {};
  const out = {};
  for (const r of catalog?.rules || []) {
    if (r.kind === "loi" || r.vary === false) {
      out[r.id] = r.value;
      continue;
    }
    if (ov[r.id] !== undefined) {
      out[r.id] = ov[r.id];
      continue;
    }
    const sk = r.settings_key;
    if (sk && settings && settings[sk] != null) {
      out[r.id] = settings[sk];
      continue;
    }
    out[r.id] = r.value;
  }
  return out;
}

export function valuesFromChosen(chosen) {
  const out = {};
  Object.entries(chosen || {}).forEach(([id, spec]) => {
    out[id] = spec && typeof spec === "object" && "value" in spec ? spec.value : spec;
  });
  return out;
}

export function valuesFromPreview(preview) {
  return valuesFromChosen(preview?.chosen);
}

export function matchesProfile(catalog, profile, values) {
  if (!catalog || !profile) return false;
  const base = profileBase(catalog, profile);
  return varyRules(catalog).every((r) => sameValue(
    coerceValue(r, values[r.id]),
    coerceValue(r, base[r.id]),
  ));
}

export function matchingProfile(catalog, values) {
  for (const name of PROFILE_ORDER) {
    if (catalog?.profiles?.[name] && matchesProfile(catalog, name, values)) return name;
  }
  return null;
}

export function buildLaunchPayload(catalog, profile, values, settings) {
  const baseProfile = profile || "cdc_default";
  const resolved = backendResolved(catalog, baseProfile, settings);
  const rules = {};
  for (const r of varyRules(catalog)) {
    if (r.legacy || values[r.id] === undefined) continue;
    const intended = coerceValue(r, values[r.id]);
    if (!sameValue(intended, coerceValue(r, resolved[r.id]))) {
      rules[r.id] = intended;
    }
  }
  return { profile: baseProfile, rules };
}

export function cdcDefaultOf(catalog, ruleId) {
  const rule = (catalog?.rules || []).find((r) => r.id === ruleId);
  return rule ? rule.value : undefined;
}

export function differsFromCdc(catalog, chosen) {
  const diffs = [];
  const same = [];
  Object.entries(chosen || {}).forEach(([id, spec]) => {
    const value = spec && typeof spec === "object" && "value" in spec ? spec.value : spec;
    const cdc = cdcDefaultOf(catalog, id);
    const row = { id, ...(typeof spec === "object" ? spec : { value }), value };
    if (cdc !== undefined && !sameValue(value, cdc)) diffs.push(row);
    else same.push(row);
  });
  return { diffs, same };
}

export function sourceLabel(source, t) {
  const key = {
    catalog: "rulesSourceCatalog",
    profile: "rulesSourceProfile",
    settings: "rulesSourceSettings",
    override: "rulesSourceOverride",
    loi: "rulesSourceLoi",
  }[source] || "rulesSourceCatalog";
  return t(key);
}
