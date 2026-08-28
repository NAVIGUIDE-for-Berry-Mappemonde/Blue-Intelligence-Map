import { useEffect, useRef, useState } from "react";
import { Check, Download, FileDown, Upload, X } from "lucide-react";
import api, { BACKEND_URL } from "../api";

// Phase 6 — Extraction (project-swarm) section migrated to Audit → Projects card.
// SettingsPanel now only hosts transverse concerns:
//   - Documentation (manual EN/FR)
//   - Data (import GeoJSON / contextual export / clear projects)
//   - Marine filtering (coast distance, marine score)
//   - Map (min zoom, max markers)
//   - API keys (LLM + TinyFish)
// The panel typography adopts the active mode's accent (cyan / red / amber).

function Field({ label, children }) {
  return (
    <div>
      <label className="block font-mono text-[10px] uppercase tracking-wide text-slate-500 mb-1">{label}</label>
      {children}
    </div>
  );
}

const inputCls = "w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent/50";

// Phase 6 — contextual GeoJSON export URL, driven by the currently active mode.
const EXPORT_URLS = {
  projects:    "/api/export/geojson",
  marinas:     "/api/export/marinas.geojson",
  formalities: "/api/export/poe.geojson",
};

// 2026-08-24 bug-fix — import endpoint per mode. Formalities (PoE) data is
// fully regenerable from the pipeline, so it has no import endpoint.
const IMPORT_URLS = {
  projects:    "/import/geojson",
  marinas:     "/import/marinas.geojson",
};

const IMPORT_TOTAL_KEY = {
  projects:    "total_projects",
  marinas:     "total_marinas",
};

export default function SettingsPanel({ t, mode, settings, onSaved, onImported, onProjectsCleared, onClose }) {
  const [form, setForm] = useState(null);
  const [saved, setSaved] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    if (settings) setForm({ ...settings, openrouter_api_key: "", tinyfish_api_key: "" });
  }, [settings]);

  if (!form) return null;

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    const body = { ...form };
    delete body.openrouter_api_key_set;
    delete body.tinyfish_api_key_set;
    ["min_zoom", "max_markers"].forEach(
      (k) => { body[k] = parseInt(body[k], 10) || undefined; });
    ["max_coast_km", "min_marine_score"].forEach((k) => { body[k] = parseFloat(body[k]); });
    await api.put("/settings", body);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    onSaved();
  };

  const dl = (l) => window.open(`${BACKEND_URL}/api/manual?lang=${l}`, "_blank");

  const importFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const currentMode = mode || "projects";
    if (currentMode === "formalities") {
      alert("Import non supporté pour le mode Formalités — les Ports d'Entrée se régénèrent via le pipeline (vue Audit).");
      return;
    }
    setImporting(true);
    const importUrl = IMPORT_URLS[currentMode] || IMPORT_URLS.projects;
    const totalKey = IMPORT_TOTAL_KEY[currentMode] || IMPORT_TOTAL_KEY.projects;
    try {
      const text = await file.text();
      const fc = JSON.parse(text);
      const first = (fc && fc.features && fc.features[0] && fc.features[0].properties) || {};
      const isProj = "title" in first && "url" in first;
      const isMar = "source" in first && "priority" in first;
      const looksLike = isMar ? "marinas" : isProj ? "projects" : "unknown";
      if (looksLike !== "unknown" && looksLike !== currentMode) {
        throw new Error(
          `Fichier détecté comme "${looksLike}" mais le mode actif est "${currentMode}". ` +
            `Bascule dans le bon mode avant d'importer.`,
        );
      }
      const { data } = await api.post(importUrl, fc, { timeout: 180000 });
      const totalLabel = currentMode === "marinas" ? "Total marinas" : t("totalN");
      alert(
        `${t("importDone")}\n` +
          `• ${t("importedN")}: ${data.imported}\n` +
          `• ${t("mergedN")}: ${data.merged}\n` +
          `• ${t("skippedN")}: ${data.skipped_existing}\n` +
          `• ${t("invalidN")}: ${data.invalid}\n` +
          `• ${totalLabel}: ${data[totalKey]}`,
      );
      if (onImported) onImported(currentMode);
    } catch (err) {
      alert(`${t("importError")}: ${err.response?.data?.detail || err.message}`);
    } finally {
      setImporting(false);
    }
  };

  const currentMode = mode || "projects";
  const exportUrl = EXPORT_URLS[currentMode] || EXPORT_URLS.projects;

  return (
    <aside className="w-[320px] shrink-0 border-l border-line bg-surface overflow-y-auto" data-testid="settings-panel">
      <div className="flex items-center justify-between px-4 py-3 border-b border-line sticky top-0 bg-surface z-10">
        <h3 className="font-heading font-bold text-sm text-accent">{t("settings")}</h3>
        <div className="flex items-center gap-2">
          {saved && (
            <span data-testid="settings-autosaved-hint" className="flex items-center gap-1 font-mono text-[9px] uppercase tracking-wide text-bio">
              <Check size={11} /> {t("saved")}
            </span>
          )}
          <button data-testid="settings-close-btn" onClick={onClose} className="text-slate-500 hover:text-accent"><X size={15} /></button>
        </div>
      </div>
      <div className="p-4 space-y-5">
        {/* Docs */}
        <section>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent/70 mb-2">{t("downloads")}</p>
          <div className="flex gap-2">
            <button data-testid="manual-en-btn" onClick={() => dl("en")}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 text-[11px] border border-line rounded-sm text-slate-300 hover:bg-raised hover:text-accent">
              <FileDown size={11} /> {t("manual")} EN
            </button>
            <button data-testid="manual-fr-btn" onClick={() => dl("fr")}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 text-[11px] border border-line rounded-sm text-slate-300 hover:bg-raised hover:text-accent">
              <FileDown size={11} /> {t("manual")} FR
            </button>
          </div>
        </section>

        {/* Data import + contextual export */}
        <section>
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent/70 mb-2">{t("dataSection")}</p>
          <input ref={fileRef} data-testid="import-geojson-input" type="file" accept=".geojson,.json,application/geo+json,application/json"
            className="hidden" onChange={importFile} />
          <button data-testid="import-geojson-btn" onClick={() => fileRef.current?.click()} disabled={importing}
            className="w-full flex items-center justify-center gap-1.5 py-2 text-xs font-semibold border border-accent/40 text-accent rounded-sm hover:bg-accent/10 disabled:opacity-40"
            title={t("importGeojson") + " → " + t("mode" + currentMode.charAt(0).toUpperCase() + currentMode.slice(1))}>
            <Upload size={12} /> {importing ? t("importing") : t("importGeojson")}
          </button>
          <p data-testid="settings-import-context-hint" className="mt-1 font-mono text-[9px] uppercase tracking-wide text-slate-500">
            {t("settingsImportContextHint")} <span className="text-accent">· {t("mode" + currentMode.charAt(0).toUpperCase() + currentMode.slice(1))}</span>
          </p>
          {/* Phase 6 — single contextual export button. URL follows the active mode. */}
          <button data-testid="settings-export-btn"
            onClick={() => window.open(`${BACKEND_URL}${exportUrl}`, "_blank")}
            className="w-full flex items-center justify-center gap-1.5 py-2 mt-2 text-xs font-semibold border border-accent/40 text-accent rounded-sm hover:bg-accent/10"
            title={t("exportGeoJsonTooltip")}
          >
            <Download size={12} /> {t("exportGeojson")}
          </button>
          <p data-testid="settings-export-context-hint" className="mt-1.5 font-mono text-[9px] uppercase tracking-wide text-slate-500">
            {t("settingsExportContextHint")} <span className="text-accent">· {t("mode" + currentMode.charAt(0).toUpperCase() + currentMode.slice(1))}</span>
          </p>
          {/* "Clear all projects" button removed 2026-06 per user request */}
        </section>

        {/* Phase 7 — Marine filtering block migrated to Audit → Projects card. */}

        {/* Map — transverse */}
        <section className="space-y-2.5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent/70">{t("mapSettings")}</p>
          <Field label={t("minZoom")}>
            <input data-testid="min-zoom-input" type="number" min="1" max="8" value={form.min_zoom} onChange={(e) => set("min_zoom", e.target.value)} onBlur={save} className={inputCls} />
          </Field>
          <Field label={t("maxMarkers")}>
            <input data-testid="max-markers-input" type="number" min="50" max="5000" value={form.max_markers} onChange={(e) => set("max_markers", e.target.value)} onBlur={save} className={inputCls} />
          </Field>
        </section>

        {/* API keys — transverse */}
        <section className="space-y-2.5">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-accent/70">{t("apiKeys")}</p>
          <Field label={
            <>
              {t("openrouterKey")}{" "}
              <span className={form.openrouter_api_key_set ? "text-bio" : "text-amberx"}>
                ({form.openrouter_api_key_set ? t("keySet") : t("keyNotSet")})
              </span>
            </>
          }>
            <input data-testid="openrouter-key-input" type="password" value={form.openrouter_api_key}
              placeholder={t("leavePlaceholder")}
              onChange={(e) => set("openrouter_api_key", e.target.value)} onBlur={save} className={inputCls} />
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
              onChange={(e) => set("tinyfish_api_key", e.target.value)} onBlur={save} className={inputCls} />
          </Field>
        </section>

        {/* Save button removed 2026-06 — settings now auto-save on field blur
            (see the onBlur={save} handlers above). */}
      </div>
    </aside>
  );
}
