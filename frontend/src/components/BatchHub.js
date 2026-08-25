import { useEffect, useMemo, useRef, useState } from "react";
import {
  Anchor, Check, Compass, Loader2, Play, PlayCircle, Radar, ScrollText, Sparkles, Square,
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
 *     extraction engine, gatekeeper/extract models, follow-the-money,
 *     auto-stop, rescan days
 *   - PHASE 7: Marine filtering (max coast km, min marine score) — migrated
 *     from SettingsPanel because it's projects-exclusive.
 */
const MODELS = [
  "gemini-3-flash-preview",
  "gemini-3.5-flash",
  "gemini-3.1-pro-preview",
  "gemini-2.5-flash",
  "gemini-2.5-pro",
];
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

export default function BatchHub({ t, mode, status, refresh, settings, onSettingsSaved, onFormalitiesRefresh, showAnchorages, setShowAnchorages, anchoragesCount }) {
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
        extraction_engine: settings.extraction_engine || "gemini",
        gatekeeper_model: settings.gatekeeper_model,
        extract_model: settings.extract_model,
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

  // ---- Phase 8 — ZEE crossings (moved from the sidebar to the SIA card, 2026-06) ----
  const [zee, setZee] = useState(null);
  const [zeeLoading, setZeeLoading] = useState(true);
  const [zeeComputing, setZeeComputing] = useState(false);
  const [zeeError, setZeeError] = useState(null);
  const [zeeTriggering, setZeeTriggering] = useState(false);
  const [zeeTriggerResult, setZeeTriggerResult] = useState(null);
  const [territoriesData, setTerritoriesData] = useState(null);

  const territoryByCode = useMemo(() => {
    const acc = {};
    for (const terr of territoriesData?.territories || []) acc[terr.code] = terr;
    return acc;
  }, [territoriesData]);

  const fetchZee = async () => {
    try {
      const { data } = await api.get("/zee/crossings");
      setZee(data);
      setZeeError(null);
    } catch (e) {
      // 404 = not computed yet (expected); surface any other failure
      if (e?.response?.status !== 404) setZeeError(e?.message || "request failed");
    } finally {
      setZeeLoading(false);
    }
  };

  useEffect(() => {
    if (mode !== "formalities") return;
    fetchZee();
    api.get("/territories").then((r) => setTerritoriesData(r.data)).catch(() => {});
  }, [mode]);

  const detectZee = async () => {
    if (zeeComputing) return;
    setZeeError(null);
    setZeeComputing(true);
    try {
      await api.post("/zee/compute", {});
    } catch (e) {
      if (e?.response?.status !== 409) {
        setZeeError(e?.message || "failed");
        setZeeComputing(false);
        return;
      }
    }
    // Poll status until done (max ~5 min — first run downloads/parses EEZ polygons)
    for (let i = 0; i < 150; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const { data } = await api.get("/zee/compute/status");
        if (!data.running) {
          if (data.error) setZeeError(data.error);
          await fetchZee();
          break;
        }
      } catch (_) { /* transient */ }
    }
    setZeeComputing(false);
  };

  const triggerZeeFormalities = async () => {
    if (zeeTriggering) return;
    setZeeTriggering(true);
    setZeeTriggerResult(null);
    try {
      const { data } = await api.post("/zee/trigger-formalities");
      setZeeTriggerResult(data);
      if (onFormalitiesRefresh) onFormalitiesRefresh();
    } catch (e) {
      setZeeTriggerResult({ error: e?.message || "failed" });
    } finally {
      setZeeTriggering(false);
    }
  };
  // ---- Formalities — generate batch ----
  const [formalitiesBatchStatus, setFormalitiesBatchStatus] = useState(null);
  const [formalitiesBatchStarting, setFormalitiesBatchStarting] = useState(false);
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
        const { data } = await api.get("/formalities/generate-batch/status");
        if (!alive) return;
        setFormalitiesBatchStatus(data);
        if (data.running || (wasRunning && !data.running)) {
          if (onFormalitiesRefresh) onFormalitiesRefresh();
        }
        wasRunning = data.running;
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.formalitiesBatch = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.formalitiesBatch); };
  }, [mode, onFormalitiesRefresh]);

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
  const startFormalitiesBatch = async () => {
    if (formalitiesBatchStarting || formalitiesBatchStatus?.running) return;
    if (!window.confirm(t("formalitiesBatchConfirm"))) return;
    setFormalitiesBatchStarting(true);
    try { await api.post("/formalities/generate-batch"); }
    catch (e) { console.warn("formalities batch start failed", e); }
    finally { setTimeout(() => setFormalitiesBatchStarting(false), 800); }
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
          <div>
            <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
              {t("auditFormalitiesBatch")}
            </label>
            <button
              data-testid="audit-formalities-batch-btn"
              onClick={startFormalitiesBatch}
              disabled={formalitiesBatchStarting || formalitiesBatchStatus?.running}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-amberx/50 bg-amberx/10 hover:bg-amberx/20 disabled:opacity-70 disabled:cursor-not-allowed text-amberx font-semibold text-xs rounded-sm"
            >
              {formalitiesBatchStatus?.running ? (
                <><Loader2 size={13} className="animate-spin" /> {formalitiesBatchStatus.progress ?? 0}{formalitiesBatchStatus.total ? "/" + formalitiesBatchStatus.total : ""}</>
              ) : (
                <><Sparkles size={13} /> {t("formalitiesBatchStart")}</>
              )}
            </button>
          </div>
          {formalitiesBatchStatus?.logs_tail && formalitiesBatchStatus.logs_tail.length > 0 && (
            <div
              data-testid="audit-formalities-batch-logs"
              className="text-[9px] font-mono text-slate-500 max-h-32 overflow-y-auto leading-relaxed bg-abyss/60 border border-line rounded-sm px-2 py-1"
            >
              {formalitiesBatchStatus.logs_tail.slice(-8).map((l, i) => (
                <div key={i} className="truncate">{l}</div>
              ))}
            </div>
          )}
          {formalitiesBatchStatus?.results && formalitiesBatchStatus.results.length > 0 && (
            <div className="text-[9px] font-mono text-slate-400 max-h-24 overflow-y-auto leading-relaxed">
              {formalitiesBatchStatus.results.slice(-8).map((r, i) => (
                <div key={i} className="truncate">
                  <span className={r.status === "ia" ? "text-bio" : r.status === "verifiee" ? "text-bio" : r.status === "ia_sans_source" ? "text-amberx" : "text-slate-500"}>
                    ●
                  </span> {r.territory_code} · {r.status || r.error?.slice(0, 40) || "?"}
                </div>
              ))}
            </div>
          )}

          {/* Phase 8 — ZEE crossings (moved here from the sidebar, 2026-06) */}
          <div className="pt-3 border-t border-line" data-testid="zee-section">
            <div className="flex items-center gap-2 mb-2">
              <Radar size={13} className="text-amberx" />
              <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">{t("zeeTitle")}</span>
              {zee?.summary && (
                <span className="ml-auto font-mono text-[9px] text-slate-500" data-testid="zee-summary">
                  {zee.summary.total_crossings} {t("zeeCrossings")} · {zee.summary.unique_territories} {t("zeeTerritories")}
                </span>
              )}
            </div>
            <button
              data-testid="zee-detect-btn"
              onClick={detectZee}
              disabled={zeeComputing}
              className="w-full flex items-center justify-center gap-2 px-3 py-1.5 border border-amberx/40 bg-amberx/10 hover:bg-amberx/20 disabled:opacity-60 disabled:cursor-not-allowed text-amberx font-semibold text-xs rounded-sm"
            >
              {zeeComputing
                ? <><Loader2 size={12} className="animate-spin" /> {t("zeeDetecting")}</>
                : <><Radar size={12} /> {t("zeeDetect")}</>}
            </button>
            {zeeError && (
              <p className="mt-1.5 text-[10px] text-alert font-mono" data-testid="zee-error">{t("zeeError")}: {String(zeeError).slice(0, 120)}</p>
            )}
            {zeeLoading && !zee && (
              <p className="mt-1.5 text-[10px] text-slate-500 font-mono animate-pulse">…</p>
            )}
            {!zee && !zeeLoading && !zeeComputing && !zeeError && (
              <p className="mt-1.5 text-[10px] text-slate-500 leading-relaxed">{t("zeeEmpty")}</p>
            )}
            {zee?.crossings?.length > 0 && (
              <>
                <div
                  className="mt-2 max-h-72 overflow-y-auto border border-line rounded-sm bg-abyss/50 divide-y divide-line/60"
                  data-testid="zee-crossings-list"
                >
                  {zee.crossings.map((c) => {
                    const terr = c.territory_code ? territoryByCode[c.territory_code] : null;
                    const isFr = !!c.territory_code;
                    return (
                      <div key={`${c.order}-${c.geoname}`} className="px-2 py-1.5 flex items-start gap-1.5">
                        <span className="font-mono text-[9px] text-slate-600 mt-0.5 w-5 shrink-0">#{c.order}</span>
                        <span className="text-sm leading-none mt-0.5 shrink-0">{terr?.flag_emoji || "🌐"}</span>
                        <div className="flex-1 min-w-0">
                          <div className={`text-[11px] truncate ${isFr ? "text-slate-100" : "text-slate-400"}`}>
                            {terr?.name_fr || c.geoname}
                          </div>
                          <div className="font-mono text-[9px] text-slate-500 truncate">
                            {isFr ? (c.pol_type && c.pol_type !== "200NM" ? c.pol_type : "ZEE FR") : `${t("zeeForeign")} · ${c.sovereign || ""}`}
                            {" · "}{t("zeeEntry")} {Number(c.entry_lat).toFixed(2)},{Number(c.entry_lon).toFixed(2)}
                            {c.intersection_length_nm ? ` · ~${Math.round(c.intersection_length_nm)} NM` : ""}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <button
                  data-testid="zee-trigger-btn"
                  onClick={triggerZeeFormalities}
                  disabled={zeeTriggering}
                  className="mt-2 w-full flex items-center justify-center gap-2 px-3 py-1.5 border border-bio/40 bg-bio/10 hover:bg-bio/20 disabled:opacity-60 disabled:cursor-not-allowed text-bio font-semibold text-[11px] rounded-sm"
                >
                  {zeeTriggering
                    ? <><Loader2 size={12} className="animate-spin" /> {t("zeeTriggering")}</>
                    : <><Sparkles size={12} /> {t("zeeTrigger")}</>}
                </button>
                {zeeTriggerResult && !zeeTriggerResult.error && (
                  <p className="mt-1.5 text-[9px] font-mono text-slate-400 leading-relaxed" data-testid="zee-trigger-result">
                    ✓ {zeeTriggerResult.triggered?.length || 0} {t("zeeTriggered")} · {zeeTriggerResult.skipped_uptodate?.length || 0} {t("zeeUpToDate")}
                  </p>
                )}
                {zeeTriggerResult?.error && (
                  <p className="mt-1.5 text-[9px] font-mono text-alert">{String(zeeTriggerResult.error).slice(0, 100)}</p>
                )}
              </>
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
              <select
                data-testid="extraction-engine-select"
                value={form.extraction_engine || "gemini"}
                onChange={(e) => set("extraction_engine", e.target.value)}
                className={smallInput}
              >
                <option value="gemini">Gemini (via Emergent LLM key)</option>
                <option value="gpt">GPT (via Emergent LLM key)</option>
                <option value="claude">Claude (via Emergent LLM key)</option>
                <option value="openrouter">OpenRouter</option>
              </select>
            </div>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("gatekeeperModel")}</label>
              <select data-testid="gatekeeper-model-select" value={form.gatekeeper_model} onChange={(e) => set("gatekeeper_model", e.target.value)} className={smallInput}>
                {MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="block font-mono text-[9px] uppercase tracking-wide text-slate-500 mb-1">{t("extractModel")}</label>
              <select data-testid="extract-model-select" value={form.extract_model} onChange={(e) => set("extract_model", e.target.value)} className={smallInput}>
                {MODELS.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
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
