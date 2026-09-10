import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import api from "../../api";

// Console → Clés API. Section déplacée depuis Settings (2026-09) : les clés
// ne sont visibles / modifiables que par l'admin, comme le reste de la
// Console. Chaque champ s'enregistre au blur ; vide = clé actuelle conservée.

const KEY_FIELDS = [
  { field: "nvidia_api_key", labelKey: "nvidiaKey", setFlag: "nvidia_api_key_set", testid: "nvidia-key-input", hintKey: "nvidiaKeyHint" },
  { field: "openrouter_api_key", labelKey: "openrouterKey", setFlag: "openrouter_api_key_set", testid: "openrouter-key-input" },
  { field: "tinyfish_api_key", labelKey: "tinyfishKey", setFlag: "tinyfish_api_key_set", testid: "tinyfish-key-input" },
  { field: "serper_api_key", labelKey: "serperKey", setFlag: "serper_api_key_set", testid: "serper-key-input" },
  { field: "anthropic_api_key", labelKey: "anthropicKey", setFlag: "anthropic_api_key_set", testid: "anthropic-key-input" },
];

const inputCls = "w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent/50";

export default function ApiKeysPanel({ t, settings, onSaved }) {
  const [values, setValues] = useState({});
  const [saved, setSaved] = useState(false);

  useEffect(() => { setValues({}); }, [settings]);

  if (!settings) {
    return <p className="font-mono text-[10px] text-slate-500">…</p>;
  }

  const saveKey = async (field) => {
    const v = (values[field] || "").trim();
    if (!v) return;
    try {
      await api.put("/settings", { [field]: v });
      setValues((prev) => ({ ...prev, [field]: "" }));
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      onSaved && onSaved();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    }
  };

  return (
    <div className="space-y-2.5" data-testid="console-api-keys">
      <div className="flex items-center justify-between">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent/70">{t("apiKeys")}</p>
        {saved && (
          <span data-testid="api-keys-saved-hint" className="flex items-center gap-1 font-mono text-[9px] uppercase tracking-wide text-bio">
            <Check size={11} /> {t("saved")}
          </span>
        )}
      </div>
      {KEY_FIELDS.map(({ field, labelKey, setFlag, testid, hintKey }) => (
        <div key={field}>
          <label className="block font-mono text-[10px] uppercase tracking-wide text-slate-500 mb-1">
            {t(labelKey)}{" "}
            <span className={settings[setFlag] ? "text-bio" : "text-amberx"}>
              ({settings[setFlag] ? t("keySet") : t("keyNotSet")})
            </span>
          </label>
          <input
            data-testid={testid}
            type="password"
            value={values[field] || ""}
            placeholder={t("leavePlaceholder")}
            onChange={(e) => setValues((prev) => ({ ...prev, [field]: e.target.value }))}
            onBlur={() => saveKey(field)}
            className={inputCls}
          />
          {hintKey && (
            <p className="mt-1 font-mono text-[9px] text-slate-500 leading-relaxed">{t(hintKey)}</p>
          )}
        </div>
      ))}
      {settings.anthropic_api_key_set && (
        <p data-testid="claude-spend-hint" className="font-mono text-[9px] text-slate-400">
          {t("claudeSpend")}: ${Number(settings.claude_spend_usd || 0).toFixed(4)}
          {settings.claude_calls ? ` · ${settings.claude_calls} appels` : ""}
        </p>
      )}
    </div>
  );
}
