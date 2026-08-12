import { useEffect, useState } from "react";
import { Check, FileDown, X } from "lucide-react";
import api from "../api";

const MODELS = [
  "gemini-3-flash-preview",
  "gemini-3.5-flash",
  "gemini-3.1-pro-preview",
  "gemini-2.5-flash",
  "gemini-2.5-pro",
];

function Field({ label, children }) {
  return (
    <div>
      <label className="block font-mono text-[10px] uppercase tracking-wide text-slate-500 mb-1">{label}</label>
      {children}
    </div>
  );
}

const inputCls = "w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-cyan-500";

export default function SettingsPanel({ t, lang, settings, onSaved, onClose }) {
  const [form, setForm] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) setForm({ ...settings, gemini_api_key: "", tinyfish_api_key: "" });
  }, [settings]);

  if (!form) return null;

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    const body = { ...form };
    delete body.gemini_api_key_set;
    delete body.tinyfish_api_key_set;
    ["tinyfish_agents", "extract_concurrency", "test_max_urls_per_seed", "full_max_urls_per_seed", "min_zoom", "max_markers", "max_partner_orgs"].forEach(
      (k) => { body[k] = parseInt(body[k], 10) || undefined; });
    ["max_coast_km", "min_marine_score"].forEach((k) => { body[k] = parseFloat(body[k]); });
    await api.put("/settings", body);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    onSaved();
  };

  const dl = (l) => window.open(`${process.env.REACT_APP_BACKEND_URL}/api/manual?lang=${l}`, "_blank");

  return (
    <aside className="w-[320px] shrink-0 border-l border-line bg-surface overflow-y-auto" data-testid="settings-panel">
      <div className="flex items-center justify-between px-4 py-3 border-b border-line sticky top-0 bg-surface z-10">
        <h3 className="font-heading font-bold text-sm text-white">{t("settings")}</h3>
        <button data-testid="settings-close-btn" onClick={onClose} className="text-slate-500 hover:text-slate-200"><X size={15} /></button>
      </div>
      <div className="p-4 space-y-5">
        {/* Docs */}
        <section>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/70 mb-2">{t("downloads")}</p>
          <div className="flex gap-2">
            <button data-testid="manual-en-btn" onClick={() => dl("en")}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 text-[11px] border border-line rounded-sm text-slate-300 hover:bg-raised">
              <FileDown size={11} /> {t("manual")} EN
            </button>
            <button data-testid="manual-fr-btn" onClick={() => dl("fr")}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 text-[11px] border border-line rounded-sm text-slate-300 hover:bg-raised">
              <FileDown size={11} /> {t("manual")} FR
            </button>
          </div>
        </section>

        {/* Marine filtering */}
        <section className="space-y-2.5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/70">{t("marineFiltering")}</p>
          <Field label={t("maxCoastKm")}>
            <input data-testid="max-coast-km-input" type="number" value={form.max_coast_km} onChange={(e) => set("max_coast_km", e.target.value)} className={inputCls} />
          </Field>
          <Field label={`${t("minMarineScore")} (${form.min_marine_score})`}>
            <input data-testid="min-marine-score-input" type="range" min="0" max="1" step="0.05" value={form.min_marine_score}
              onChange={(e) => set("min_marine_score", e.target.value)} className="w-full accent-cyan-400" />
          </Field>
        </section>

        {/* Extraction */}
        <section className="space-y-2.5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/70">{t("extraction")}</p>
          <Field label={t("tinyfishAgents")}>
            <select data-testid="tinyfish-agents-select" value={form.tinyfish_agents} onChange={(e) => set("tinyfish_agents", e.target.value)} className={inputCls}>
              <option value={1}>1</option>
              <option value={2}>2</option>
            </select>
          </Field>
          <Field label={`${t("concurrency")} (${form.extract_concurrency})`}>
            <input data-testid="concurrency-input" type="range" min="1" max="20" value={form.extract_concurrency}
              onChange={(e) => set("extract_concurrency", e.target.value)} className="w-full accent-cyan-400" />
          </Field>
          <Field label={t("gatekeeperModel")}>
            <select data-testid="gatekeeper-model-select" value={form.gatekeeper_model} onChange={(e) => set("gatekeeper_model", e.target.value)} className={inputCls}>
              {MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </Field>
          <Field label={t("extractModel")}>
            <select data-testid="extract-model-select" value={form.extract_model} onChange={(e) => set("extract_model", e.target.value)} className={inputCls}>
              {MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </Field>
          <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
            <input data-testid="follow-money-checkbox" type="checkbox" checked={!!form.follow_the_money}
              onChange={(e) => set("follow_the_money", e.target.checked)} className="accent-cyan-400" />
            {t("followMoney")}
          </label>
          {form.follow_the_money && (
            <Field label={t("maxPartnerOrgs")}>
              <input data-testid="max-partner-orgs-input" type="number" min="1" max="20" value={form.max_partner_orgs}
                onChange={(e) => set("max_partner_orgs", e.target.value)} className={inputCls} />
            </Field>
          )}
        </section>

        {/* Map */}
        <section className="space-y-2.5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/70">{t("mapSettings")}</p>
          <Field label={t("minZoom")}>
            <input data-testid="min-zoom-input" type="number" min="1" max="8" value={form.min_zoom} onChange={(e) => set("min_zoom", e.target.value)} className={inputCls} />
          </Field>
          <Field label={t("maxMarkers")}>
            <input data-testid="max-markers-input" type="number" min="50" max="5000" value={form.max_markers} onChange={(e) => set("max_markers", e.target.value)} className={inputCls} />
          </Field>
        </section>

        {/* API keys */}
        <section className="space-y-2.5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/70">{t("apiKeys")}</p>
          <Field label={
            <>
              {t("geminiKey")}{" "}
              <span className={form.gemini_api_key_set ? "text-bio" : "text-amberx"}>
                ({form.gemini_api_key_set ? t("keySet") : t("keyNotSet")})
              </span>
            </>
          }>
            <input data-testid="gemini-key-input" type="password" value={form.gemini_api_key}
              placeholder={t("leavePlaceholder")}
              onChange={(e) => set("gemini_api_key", e.target.value)} className={inputCls} />
          </Field>
          <Field label={
            <>
              {t("tinyfishKey")}{" "}
              <span className={form.tinyfish_api_key_set ? "text-bio" : "text-amberx"}>
                ({form.tinyfish_api_key_set ? t("keySet") : t("keyNotSet")})
              </span>
            </>
          }>
            <input data-testid="tinyfish-key-input" type="password" value={form.tinyfish_api_key}
              placeholder={t("leavePlaceholder")}
              onChange={(e) => set("tinyfish_api_key", e.target.value)} className={inputCls} />
          </Field>
        </section>

        <button data-testid="save-settings-btn" onClick={save}
          className="w-full flex items-center justify-center gap-2 py-2 font-heading font-bold text-sm rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25">
          {saved ? <><Check size={14} /> {t("saved")}</> : t("save")}
        </button>
      </div>
    </aside>
  );
}
