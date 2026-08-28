import { useEffect, useRef, useState } from "react";
import {
  Anchor, Check, Loader2, Play, PlayCircle, Radar, Sparkles, Square,
} from "lucide-react";
import api from "../api";

/**
 * BatchHub — Phase 7 contextual audit block.
 *
 * The audit view now shows ONLY the card matching the active mode
 * (projects → Projects card, marinas → Marinas card, formalities → Formalities card).
 * This keeps the operator focused on the mode they're auditing.
 *
 * Projects card hosts (Phase 6 + Phase 7):
 *   - Swarm ops (Test/Full, Clear DB, Deploy/Stop, log stream)
 *   - Project-swarm-exclusive settings: TinyFish agents, concurrency,
 *     follow-the-money, auto-stop, rescan days
 *   - PHASE 7: Marine filtering (max coast km, min marine score) — migrated
 *     from SettingsPanel because it's projects-exclusive.
 *
 * All LLM calls go through OpenRouter (model set server-side via OPENROUTER_MODEL).
 */
const smallInput = "w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent/50";

/** Card shell — extracted from BatchHub to keep component identity stable across renders. */
function CardShell({ title, icon, borderCls, children }) {
  // 2026-06 UX: header row only when a title is provided — the mode name is
  // already visible in the top nav + left sidebar, no need to repeat it here.
  return (
    <div className={`border bg-surface flex flex-col ${borderCls}`}>
      {title && (
        <div className="px-4 py-2.5 border-b border-line flex items-center gap-2">
          {icon}
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-400">{title}</p>
        </div>
      )}
      <div className="p-4 space-y-3 flex-1">{children}</div>
    </div>
  );
}

export default function BatchHub({ t, mode, status, refresh, settings, onSettingsSaved, onPoeRefresh, showAnchorages, setShowAnchorages, anchoragesCount }) {
  // ---- Projects — swarm controls ----
  const [swarmMode, setSwarmMode] = useState("test");
  const [clearDb, setClearDb] = useState(false);
  const [busy, setBusy] = useState(false);
  const running = status?.running;
  // Extraction + marine filtering settings form
  const [form, setForm] = useState(null);
  const [savedFlag, setSavedFlag] = useState(false);

  useEffect(() => {
    if (settings) {
      setForm((f) => f || {
        tinyfish_agents: settings.tinyfish_agents,
        extract_concurrency: settings.extract_concurrency,
        follow_the_money: !!settings.follow_the_money,
        max_partner_orgs: settings.max_partner_orgs,
        saturation_limit: settings.saturation_limit,
        rescan_after_days: settings.rescan_after_days,
        // Phase 7 — marine filtering migrated here
        max_coast_km: settings.max_coast_km,
        min_marine_score: settings.min_marine_score,
      });
    }
  }, [settings]);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const deploy = async () => {
    setBusy(true);
    try {
      await api.post("/swarm/deploy", { mode: swarmMode, clear_db: clearDb });
      refresh && refresh();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };
  const stop = async () => {
    setBusy(true);
    try { await api.post("/swarm/stop"); refresh && refresh(); } finally { setBusy(false); }
  };
  const saveExtraction = async () => {
    if (!form) return;
    const body = { ...form };
    ["tinyfish_agents", "extract_concurrency", "max_partner_orgs", "saturation_limit"].forEach(
      (k) => { body[k] = parseInt(body[k], 10) || undefined; });
    body.rescan_after_days = parseFloat(body.rescan_after_days);
    body.max_coast_km = parseFloat(body.max_coast_km);
    body.min_marine_score = parseFloat(body.min_marine_score);
    try {
      await api.put("/settings", body);
      setSavedFlag(true);
      setTimeout(() => setSavedFlag(false), 2000);
      onSettingsSaved && onSettingsSaved();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    }
  };

  // ---- Marinas — build + enrich batch ----
  const [buildStatus, setBuildStatus] = useState(null);
  const [buildStarting, setBuildStarting] = useState(false);
  const [marinaBatchStatus, setMarinaBatchStatus] = useState(null);
  const [marinaBatchStarting, setMarinaBatchStarting] = useState(false);
  const [marinaBatchCount, setMarinaBatchCount] = useState(10);
  // Phase 8 — anchorages build + corridor toggle (shared by both scans)
  const [anchStatus, setAnchStatus] = useState(null);
  const [anchStarting, setAnchStarting] = useState(false);
  const [corridorOn, setCorridorOn] = useState(true);

  // ---- Refactor 2026-06 — PoE (formalities mode): EEZ referential + generation batch ----
  const [refStatus, setRefStatus] = useState(null);
  const [refStarting, setRefStarting] = useState(false);
  const [poeBatchStatus, setPoeBatchStatus] = useState(null);
  const [poeBatchStarting, setPoeBatchStarting] = useState(false);
  const [poeBatchCount, setPoeBatchCount] = useState(10);
  const [poeOnlyMissing, setPoeOnlyMissing] = useState(true);
  const [autoStatus, setAutoStatus] = useState(null);
  const pollRefs = useRef({});

  // Only poll for the active mode's data — saves bandwidth.
  useEffect(() => {
    if (mode !== "marinas") return;
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/marinas/build/status");
        if (alive) setBuildStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.build = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.build); };
  }, [mode]);
  useEffect(() => {
    if (mode !== "marinas") return;
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/marinas/enrich-batch/status");
        if (alive) setMarinaBatchStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.marinasBatch = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.marinasBatch); };
  }, [mode]);
  useEffect(() => {
    if (mode !== "marinas") return;
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/anchorages/build/status");
        if (alive) setAnchStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.anchBuild = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.anchBuild); };
  }, [mode]);
  useEffect(() => {
    if (mode !== "formalities") return;
    let alive = true;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/poe/referential/status");
        if (!alive) return;
        setRefStatus(data);
        if (wasRunning && !data.running && onPoeRefresh) onPoeRefresh();
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.poeRef = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.poeRef); };
  }, [mode, onPoeRefresh]);
  useEffect(() => {
    if (mode !== "formalities") return;
    let alive = true;
    let wasRunning = false;
    const check = async () => {
      try {
        const { data } = await api.get("/poe/generate-batch/status");
        if (!alive) return;
        setPoeBatchStatus(data);
        if ((data.running || wasRunning) && onPoeRefresh) onPoeRefresh();
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.poeBatch = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.poeBatch); };
  }, [mode, onPoeRefresh]);
  useEffect(() => {
    if (mode !== "formalities") return;
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/poe/auto-refresh/status");
        if (alive) setAutoStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.poeAuto = setInterval(check, 20000);
    return () => { alive = false; clearInterval(pollRefs.current.poeAuto); };
  }, [mode]);

  const startBuild = async () => {
    if (buildStarting || buildStatus?.running) return;
    setBuildStarting(true);
    try { await api.post("/marinas/build", { include_corridor: corridorOn, clear_before: false }); }
    catch (e) { console.warn("build start failed", e); }
    finally { setTimeout(() => setBuildStarting(false), 800); }
  };
  const startAnchBuild = async () => {
    if (anchStarting || anchStatus?.running) return;
    setAnchStarting(true);
    try { await api.post("/anchorages/build", { include_corridor: corridorOn, clear_before: false }); }
    catch (e) { console.warn("anchorages build start failed", e); }
    finally { setTimeout(() => setAnchStarting(false), 800); }
  };
  const startMarinaBatch = async () => {
    if (marinaBatchStarting || marinaBatchStatus?.running || buildStatus?.running) return;
    const lim = parseInt(marinaBatchCount, 10);
    if (lim === 0 && !window.confirm(t("enrichBatchAllConfirm"))) return;
    setMarinaBatchStarting(true);
    try { await api.post("/marinas/enrich-batch", { limit: lim }); }
    catch (e) { console.warn("marina batch start failed", e); }
    finally { setTimeout(() => setMarinaBatchStarting(false), 800); }
  };
  const stopMarinaBatch = async () => {
    try { await api.post("/marinas/enrich-batch/cancel"); }
    catch (e) { console.warn("marina batch cancel failed", e); }
  };
  const startPoeReferential = async () => {
    if (refStarting || refStatus?.running) return;
    setRefStarting(true);
    try { await api.post("/poe/referential/build"); }
    catch (e) { console.warn("poe referential start failed", e); }
    finally { setTimeout(() => setRefStarting(false), 800); }
  };
  const startPoeBatch = async () => {
    if (poeBatchStarting || poeBatchStatus?.running) return;
    if (!window.confirm(t("auditPoeBatchConfirm"))) return;
    setPoeBatchStarting(true);
    try {
      await api.post("/poe/generate-batch", {
        limit: parseInt(poeBatchCount, 10) || 0,
        only_missing: poeOnlyMissing,
      });
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setTimeout(() => setPoeBatchStarting(false), 800); }
  };
  const stopPoeBatch = async () => {
    try { await api.post("/poe/generate-batch/cancel"); }
    catch (e) { console.warn("poe batch cancel failed", e); }
  };

  // ---- Card wrapper (single card, full width — CardShell moved out for stability) ----

  // ---- Render only the active mode's card ----
  if (mode === "marinas") {
    return (
      <div data-testid="audit-batch-hub" data-mode-card="marinas">
        <CardShell borderCls="border-alert/40">
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("auditMarinasBuild")}
            </label>
            <label className="flex items-center gap-2 mb-2 text-xs text-slate-400 cursor-pointer select-none">
              <input
                data-testid="audit-corridor-toggle"
                type="checkbox"
                checked={corridorOn}
                onChange={(e) => setCorridorOn(e.target.checked)}
                className="accent-teal-400"
              />
              {t("auditCorridorToggle")}
            </label>
            <button
              data-testid="audit-marinas-scan-btn"
              onClick={startBuild}
              disabled={buildStarting || buildStatus?.running}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-alert/50 bg-alert/10 hover:bg-alert/20 disabled:opacity-70 disabled:cursor-not-allowed text-alert font-semibold text-xs rounded-sm"
            >
              {buildStatus?.running ? (
                <><Loader2 size={13} className="animate-spin" /> {buildStatus.progress}/{buildStatus.total}</>
              ) : (
                <><PlayCircle size={13} /> {t("marinasScan")}</>
              )}
            </button>
            {buildStatus?.summary && !buildStatus.running && (
              <p className="mt-1.5 text-[9px] font-mono text-slate-500 leading-relaxed">
                ✓ OSM {buildStatus.summary.by_source?.openstreetmap ?? 0} · SHOM {buildStatus.summary.by_source?.shom ?? 0} · Curated {buildStatus.summary.by_source?.curated ?? 0}
              </p>
            )}
            {/* Phase 8 — anchorages scan (same ±25 NM corridor logic) */}
            <button
              data-testid="audit-anchorages-scan-btn"
              onClick={startAnchBuild}
              disabled={anchStarting || anchStatus?.running}
              className="mt-2 w-full flex items-center justify-center gap-2 px-3 py-2 border border-teal-400/50 bg-teal-400/10 hover:bg-teal-400/20 disabled:opacity-70 disabled:cursor-not-allowed text-teal-300 font-semibold text-xs rounded-sm"
            >
              {anchStatus?.running ? (
                <><Loader2 size={13} className="animate-spin" /> {anchStatus.progress}/{anchStatus.total}</>
              ) : (
                <><Anchor size={13} /> {t("auditAnchoragesBuild")}</>
              )}
            </button>
            {anchStatus?.summary && !anchStatus.running && (
              <p className="mt-1.5 text-[9px] font-mono text-slate-500 leading-relaxed" data-testid="audit-anchorages-summary">
                ⚓ {anchStatus.summary.unique_after_dedup ?? 0} · bay {anchStatus.summary.by_type?.bay ?? 0} · anchorage {anchStatus.summary.by_type?.anchorage ?? 0} · berth {anchStatus.summary.by_type?.anchor_berth ?? 0}
              </p>
            )}
            {anchStatus?.error && !anchStatus.running && (
              <p className="mt-1.5 text-[9px] font-mono text-alert leading-relaxed" data-testid="audit-anchorages-error">
                ✗ {String(anchStatus.error).slice(0, 90)}
              </p>
            )}
            {anchStatus?.running && anchStatus?.logs_tail?.length > 0 && (
              <div className="mt-1.5 text-[9px] font-mono text-slate-500 max-h-16 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1">
                {anchStatus.logs_tail.slice(-4).map((l, i) => <div key={i} className="truncate">{l}</div>)}
              </div>
            )}
            {/* Anchorage layer visibility — moved here from the sidebar (2026-06) */}
            <label
              className="flex items-center gap-2 mt-2 text-xs text-slate-300 cursor-pointer select-none"
              data-testid="anchorages-toggle"
            >
              <input
                type="checkbox"
                checked={!!showAnchorages}
                onChange={(e) => setShowAnchorages && setShowAnchorages(e.target.checked)}
                className="accent-teal-400"
              />
              <span className="flex-1">{t("anchoragesToggle")}</span>
              <span className="font-mono text-[10px] uppercase tracking-widest text-teal-300/80" data-testid="anchorages-count">
                ⚓ {anchoragesCount ?? 0}
              </span>
            </label>
          </div>
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("auditMarinasEnrich")}
            </label>
            <div className="flex gap-2">
              <select
                value={marinaBatchCount}
                onChange={(e) => setMarinaBatchCount(e.target.value)}
                disabled={marinaBatchStatus?.running}
                data-testid="audit-marinas-batch-count"
                className="w-16 px-2 py-1.5 bg-raised border border-line rounded-sm text-xs text-slate-100 focus:outline-none focus:border-alert/60 disabled:opacity-60"
              >
                <option value="5">5</option>
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="0">{t("enrichBatchAllOption")}</option>
              </select>
              <button
                data-testid="audit-marinas-batch-btn"
                onClick={startMarinaBatch}
                disabled={marinaBatchStarting || marinaBatchStatus?.running || buildStatus?.running}
                className="flex-1 flex items-center justify-center gap-2 px-3 py-1.5 border border-alert/40 bg-alert/10 hover:bg-alert/20 disabled:opacity-60 disabled:cursor-not-allowed text-alert font-semibold text-xs rounded-sm"
              >
                {marinaBatchStatus?.running ? (
                  <><Loader2 size={12} className="animate-spin" /> {marinaBatchStatus.progress}/{marinaBatchStatus.total}</>
                ) : (
                  <><Sparkles size={12} /> {t("enrichBatchStart")}</>
                )}
              </button>
              {marinaBatchStatus?.running && (
                <button
                  data-testid="audit-marinas-batch-stop-btn"
                  onClick={stopMarinaBatch}
                  disabled={marinaBatchStatus?.cancelling}
                  className="flex items-center justify-center gap-1.5 px-3 py-1.5 border border-alert bg-alert/25 hover:bg-alert/40 disabled:opacity-60 text-alert font-bold text-xs rounded-sm"
                >
                  <Square size={11} /> {marinaBatchStatus?.cancelling ? "…" : "Stop"}
                </button>
              )}
            </div>
            {marinaBatchStatus?.running && marinaBatchStatus?.logs_tail && marinaBatchStatus.logs_tail.length > 0 && (
              <div
                data-testid="audit-marinas-batch-logs"
                className="mt-2 text-[9px] font-mono text-slate-500 max-h-32 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1"
              >
                {marinaBatchStatus.logs_tail.slice(-8).map((l, i) => (
                  <div key={i} className="truncate">{l}</div>
                ))}
              </div>
            )}
            {marinaBatchStatus?.results && marinaBatchStatus.results.length > 0 && (
              <div className="mt-2 text-[9px] font-mono max-h-24 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1">
                {marinaBatchStatus.results.slice(-6).map((r, i) => (
                  <div key={i} className="truncate text-slate-400">
                    <span className={r.enriched ? "text-bio" : (r.error ? "text-alert" : "text-slate-500")}>
                      {r.enriched ? "✓" : r.error ? "✗" : "·"}
                    </span> {r.name}
                    {r.source && <span className="text-slate-500"> · {r.source}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardShell>
      </div>
    );
  }

  if (mode === "formalities") {
    return (
      <div data-testid="audit-batch-hub" data-mode-card="formalities">
        <CardShell borderCls="border-amberx/40">
          {/* --- EEZ referential (VLIZ Marine Regions) --- */}
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("poeEezAttribution")}
            </label>
            <button
              data-testid="poe-referential-btn"
              onClick={startPoeReferential}
              disabled={refStarting || refStatus?.running}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-amberx/50 bg-amberx/10 hover:bg-amberx/20 disabled:opacity-70 disabled:cursor-not-allowed text-amberx font-semibold text-xs rounded-sm"
            >
              {refStatus?.running ? (
                <><Loader2 size={13} className="animate-spin" /> {t("auditPoeReferentialRunning")} {refStatus.progress}/{refStatus.total || "?"}</>
              ) : (
                <><Radar size={13} /> {t("auditPoeReferential")}</>
              )}
            </button>
            {refStatus?.running && refStatus?.logs_tail?.length > 0 && (
              <div className="mt-1.5 text-[9px] font-mono text-slate-500 max-h-16 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1" data-testid="poe-referential-logs">
                {refStatus.logs_tail.slice(-4).map((l, i) => <div key={i} className="truncate">{l}</div>)}
              </div>
            )}
            {refStatus?.summary && !refStatus.running && (
              <p className="mt-1.5 text-[9px] font-mono text-slate-500" data-testid="poe-referential-summary">
                ✓ {refStatus.summary.zones} ZEE · map {refStatus.summary.map_file_kb} Ko
              </p>
            )}
            {refStatus?.error && !refStatus.running && (
              <p className="mt-1.5 text-[9px] font-mono text-alert">✗ {String(refStatus.error).slice(0, 100)}</p>
            )}
          </div>

          {/* --- PoE generation batch --- */}
          <div className="pt-3 border-t border-line">
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("auditPoeBatch")}
            </label>
            <label className="flex items-center gap-2 mb-2 text-xs text-slate-400 cursor-pointer select-none">
              <input
                data-testid="poe-only-missing-toggle"
                type="checkbox"
                checked={poeOnlyMissing}
                onChange={(e) => setPoeOnlyMissing(e.target.checked)}
                className="accent-amber-400"
              />
              {t("auditPoeOnlyMissing")}
            </label>
            <div className="flex gap-2">
              <select
                value={poeBatchCount}
                onChange={(e) => setPoeBatchCount(e.target.value)}
                disabled={poeBatchStatus?.running}
                data-testid="poe-batch-count"
                className="w-16 px-2 py-1.5 bg-raised border border-line rounded-sm text-xs text-slate-100 focus:outline-none focus:border-amberx/60 disabled:opacity-60"
              >
                <option value="5">5</option>
                <option value="10">10</option>
                <option value="25">25</option>
                <option value="0">{t("enrichBatchAllOption")}</option>
              </select>
              <button
                data-testid="audit-formalities-batch-btn"
                onClick={startPoeBatch}
                disabled={poeBatchStarting || poeBatchStatus?.running || refStatus?.running}
                className="flex-1 flex items-center justify-center gap-2 px-3 py-1.5 border border-amberx/50 bg-amberx/10 hover:bg-amberx/20 disabled:opacity-70 disabled:cursor-not-allowed text-amberx font-semibold text-xs rounded-sm"
              >
                {poeBatchStatus?.running ? (
                  <><Loader2 size={13} className="animate-spin" /> {poeBatchStatus.progress ?? 0}/{poeBatchStatus.total || "?"}</>
                ) : (
                  <><Sparkles size={13} /> {t("auditPoeBatch")}</>
                )}
              </button>
              {poeBatchStatus?.running && (
                <button
                  data-testid="poe-batch-stop-btn"
                  onClick={stopPoeBatch}
                  disabled={poeBatchStatus?.cancelling}
                  className="flex items-center justify-center gap-1.5 px-3 py-1.5 border border-alert bg-alert/25 hover:bg-alert/40 disabled:opacity-60 text-alert font-bold text-xs rounded-sm"
                >
                  <Square size={11} /> {poeBatchStatus?.cancelling ? "…" : "Stop"}
                </button>
              )}
            </div>
            {poeBatchStatus?.logs_tail && poeBatchStatus.logs_tail.length > 0 && poeBatchStatus.running && (
              <div
                data-testid="audit-formalities-batch-logs"
                className="mt-2 text-[9px] font-mono text-slate-500 max-h-32 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1"
              >
                {poeBatchStatus.logs_tail.slice(-8).map((l, i) => (
                  <div key={i} className="truncate">{l}</div>
                ))}
              </div>
            )}
            {poeBatchStatus?.results && poeBatchStatus.results.length > 0 && (
              <div className="mt-2 text-[9px] font-mono text-slate-400 max-h-24 overflow-y-auto leading-relaxed">
                {poeBatchStatus.results.slice(-8).map((r, i) => (
                  <div key={i} className="truncate">
                    <span className={r.status === "ia" ? "text-bio" : r.status === "ia_sans_source" ? "text-amberx" : "text-slate-500"}>
                      ●
                    </span> {r.name} · {r.status ? `${r.status} · ${r.poe_count} PoE` : (r.error?.slice(0, 40) || "?")}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* --- Auto-refresh (MD5 monitoring) --- */}
          <div className="pt-3 border-t border-line" data-testid="poe-auto-refresh-section">
            <div className="flex items-center gap-2 mb-1">
              <span className={`inline-block w-1.5 h-1.5 rounded-full ${autoStatus?.cycle_running ? "bg-amberx animate-pulse" : "bg-bio"}`} />
              <span className="font-mono text-[9px] uppercase tracking-widest text-slate-400">
                ♻ {t("poeAutoRefreshTitle")} · {autoStatus?.cycle_running ? t("poeAutoCycleRunning") : t("poeAutoActive")}
              </span>
            </div>
            <p className="text-[10px] text-slate-500 leading-relaxed">{t("poeAutoRefreshDesc")}</p>
            {autoStatus?.last_summary && (
              <p className="mt-1 font-mono text-[9px] text-slate-500" data-testid="poe-auto-refresh-summary">
                {t("poeAutoLastCycle")}: {autoStatus.last_summary.checked} {t("poeAutoChecked")} ·{" "}
                {autoStatus.last_summary.unchanged_md5} {t("poeAutoUnchangedMd5")} ·{" "}
                {autoStatus.last_summary.updated} {t("poeAutoUpdated")}
                {autoStatus.last_summary.errors_retried > 0 ? ` · ${autoStatus.last_summary.errors_retried} ${t("poeAutoErrRetried")}` : ""}
              </p>
            )}
          </div>
        </CardShell>
      </div>
    );
  }

  // Default (projects) — full swarm ops + swarm-exclusive settings + marine filtering.
  return (
    <div data-testid="audit-batch-hub" data-mode-card="projects">
      <CardShell borderCls="border-sonar/40">
        {/* Status pills */}
        <div className="flex items-center gap-2 flex-wrap">
          <span
            data-testid="swarm-status-badge"
            className={`font-mono text-[10px] px-2 py-0.5 rounded-sm border ${running ? "text-bio border-bio/40 bg-bio/5" : "text-slate-400 border-line bg-raised"}`}
          >
            {running ? t("runningStatus") : t("idle")}
          </span>
          <span
            className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${status?.tinyfish ? "text-sonar border-sonar/40" : "text-amberx border-amberx/40"}`}
          >
            {status?.tinyfish ? t("tfActive") : t("tfFallback")}
          </span>
          <span
            className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border ${status?.llm ? "text-sonar border-sonar/40" : "text-amberx border-amberx/40"}`}
            title={t("llmEngineTooltip")}
          >
            {status?.llm ? (status?.engine || "").toUpperCase() || t("llmActive") : t("llmFallback")}
          </span>
        </div>

        <div className="grid grid-cols-2 gap-px bg-line border border-line">
          <div className="bg-surface p-2">
            <p className="font-mono text-[9px] text-slate-500 uppercase">{t("active")}</p>
            <p data-testid="active-agents-count" className="font-heading font-black text-lg text-sonar">{status?.active ?? 0}</p>
          </div>
          <div className="bg-surface p-2">
            <p className="font-mono text-[9px] text-slate-500 uppercase">{t("queued")}</p>
            <p data-testid="queued-count" className="font-heading font-black text-lg text-slate-200">{status?.queued ?? 0}</p>
          </div>
        </div>

        <div className="flex gap-2">
          <button
            data-testid="mode-test-btn"
            onClick={() => setSwarmMode("test")}
            className={`flex-1 py-1.5 text-xs font-semibold border rounded-sm ${swarmMode === "test" ? "border-sonar/50 bg-sonar/10 text-sonar" : "border-line text-slate-400 hover:bg-raised"}`}
          >{t("modeTest")}</button>
          <button
            data-testid="mode-full-btn"
            onClick={() => setSwarmMode("full")}
            className={`flex-1 py-1.5 text-xs font-semibold border rounded-sm ${swarmMode === "full" ? "border-sonar/50 bg-sonar/10 text-sonar" : "border-line text-slate-400 hover:bg-raised"}`}
          >{t("modeFull")}</button>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none">
          <input data-testid="clear-db-checkbox" type="checkbox" checked={clearDb} onChange={(e) => setClearDb(e.target.checked)} className="accent-cyan-400" />
          {t("clearBefore")}
        </label>
        <button
          data-testid="deploy-swarm-btn"
          onClick={deploy}
          disabled={busy || running}
          className="w-full flex items-center justify-center gap-2 py-2 font-heading font-bold text-sm rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Play size={14} /> {t("deploy")}
        </button>
        <button
          data-testid="stop-swarm-btn"
          onClick={stop}
          disabled={busy || !running}
          className="w-full flex items-center justify-center gap-2 py-1.5 font-semibold text-xs rounded-sm border border-alert/50 text-alert hover:bg-alert/10 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <Square size={12} /> {t("stopSwarm")}
        </button>

        {/* Log stream */}
        <div className="console-scanlines bg-black/60 border border-line rounded-sm h-32 overflow-y-auto p-2 font-mono text-[10px] leading-relaxed" data-testid="swarm-log-stream">
          {(status?.logs || []).slice(-40).map((l, i) => (
            <div key={i} className={
              l.level === "error" ? "text-alert" :
              l.level === "warn" ? "text-amberx" :
              l.level === "success" ? "text-bio" : "text-sonar/80"
            }>
              <span className="text-slate-600">{l.ts?.slice(11, 19)}</span> {l.msg}
            </div>
          ))}
          {running && <span className="text-bio cursor-blink">▊</span>}
        </div>

        {/* --- Extraction settings + Marine filtering (Phase 7 migrated) --- */}
        {form && (
          <div className="pt-3 mt-2 border-t border-line space-y-2.5" data-testid="audit-extraction-settings">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/80">
              {t("auditExtractionSettingsTitle")}
            </p>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("tinyfishAgents")}</label>
              <select data-testid="tinyfish-agents-select" value={form.tinyfish_agents} onChange={(e) => set("tinyfish_agents", e.target.value)} className={smallInput}>
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">
                {t("concurrency")} ({form.extract_concurrency})
              </label>
              <input data-testid="concurrency-input" type="range" min="1" max="20" value={form.extract_concurrency}
                onChange={(e) => set("extract_concurrency", e.target.value)} className="w-full accent-cyan-400" />
            </div>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("extractionEngine")}</label>
              <div data-testid="extraction-engine-badge" className={`${smallInput} bg-black/30 text-sonar cursor-default`}>
                OpenRouter
              </div>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer select-none">
              <input data-testid="follow-money-checkbox" type="checkbox" checked={!!form.follow_the_money}
                onChange={(e) => set("follow_the_money", e.target.checked)} className="accent-cyan-400" />
              {t("followMoney")}
            </label>
            {form.follow_the_money && (
              <div>
                <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("maxPartnerOrgs")}</label>
                <input data-testid="max-partner-orgs-input" type="number" min="1" max="20" value={form.max_partner_orgs}
                  onChange={(e) => set("max_partner_orgs", e.target.value)} className={smallInput} />
              </div>
            )}
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("autoStopLimit")}</label>
              <input data-testid="saturation-limit-input" type="number" min="0" max="500" value={form.saturation_limit}
                onChange={(e) => set("saturation_limit", e.target.value)} className={smallInput} />
            </div>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("rescanDays")}</label>
              <input data-testid="rescan-days-input" type="number" min="0" max="365" step="0.5" value={form.rescan_after_days}
                onChange={(e) => set("rescan_after_days", e.target.value)} className={smallInput} />
            </div>

            {/* Phase 7 — Marine filtering (projects-exclusive) */}
            <div className="pt-3 mt-2 border-t border-line space-y-2.5" data-testid="audit-marine-filtering">
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/80">
                {t("marineFiltering")}
              </p>
              <div>
                <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("maxCoastKm")}</label>
                <input data-testid="max-coast-km-input" type="number" value={form.max_coast_km ?? ""}
                  onChange={(e) => set("max_coast_km", e.target.value)} className={smallInput} />
              </div>
              <div>
                <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">
                  {t("minMarineScore")} ({form.min_marine_score ?? "—"})
                </label>
                <input data-testid="min-marine-score-input" type="range" min="0" max="1" step="0.05" value={form.min_marine_score ?? 0}
                  onChange={(e) => set("min_marine_score", e.target.value)} className="w-full accent-cyan-400" />
              </div>
            </div>

            <button
              data-testid="save-swarm-settings-btn"
              onClick={saveExtraction}
              className="w-full flex items-center justify-center gap-2 py-1.5 text-xs font-semibold rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25"
            >
              {savedFlag ? <><Check size={12} /> {t("saved")}</> : t("save")}
            </button>
          </div>
        )}
      </CardShell>
    </div>
  );
}
