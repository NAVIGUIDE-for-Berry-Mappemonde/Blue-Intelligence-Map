export const STORAGE_KEY = "naviguide_lang_v3";
export const VALID_LANGS = new Set(["en", "fr"]);

export function readStoredLang(storage = typeof localStorage !== "undefined" ? localStorage : null) {
  const stored = storage?.getItem?.(STORAGE_KEY);
  return VALID_LANGS.has(stored) ? stored : "fr";
}
