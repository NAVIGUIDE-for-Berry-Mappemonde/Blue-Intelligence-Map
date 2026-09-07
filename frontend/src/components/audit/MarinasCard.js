import { useEffect, useRef, useState } from "react";
import { Anchor, Loader2, PlayCircle, Sparkles, Square } from "lucide-react";
import api from "../../api";
import CardShell from "./CardShell";

/**
 * MarinasCard — carte Audit du mode Marinas : build OSM/SHOM (+ mouillages),
 * batch d'enrichissement IA avec progression et logs en direct.
 * Montée uniquement quand le mode marinas est actif (polling à l'écran seulement).
 */
export default function MarinasCard({ t, showAnchorages, setShowAnchorages, anchoragesCount }) {
  const [buildStatus, setBuildStatus] = useState(null);
  const [buildStarting, setBuildStarting] = useState(false);
  const [marinaBatchStatus, setMarinaBatchStatus] = useState(null);
  const [marinaBatchStarting, setMarinaBatchStarting] = useState(false);
  const [marinaBatchCount, setMarinaBatchCount] = useState(10);
  // Phase 8 — anchorages build + corridor toggle (shared by both scans)
  const [anchStatus, setAnchStatus] = useState(null);
  const [anchStarting, setAnchStarting] = useState(false);
  const [corridorOn, setCorridorOn] = useState(true);
  const [mapsPlaceStatus, setMapsPlaceStatus] = useState(null);
  const [mapsPlaceStarting, setMapsPlaceStarting] = useState(false);
  const pollRefs = useRef({});

  useEffect(() => {
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
  }, []);
  useEffect(() => {
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
  }, []);
  useEffect(() => {
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
  }, []);
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const { data } = await api.get("/marinas/maps-place/status");
        if (alive) setMapsPlaceStatus(data);
      } catch (_) { /* transient */ }
    };
    check();
    pollRefs.current.mapsPlace = setInterval(check, 3000);
    return () => { alive = false; clearInterval(pollRefs.current.mapsPlace); };
  }, []);

  const startBuild = async () => {
    if (buildStarting || buildStatus?.running) return;
    setBuildStarting(true);
    try { await api.post("/marinas/build", { resume: true, clear_before: false }); }
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
  const startMapsPlace = async () => {
    if (mapsPlaceStarting || mapsPlaceStatus?.running) return;
    setMapsPlaceStarting(true);
    try { await api.post("/marinas/maps-place", { limit: 0, force: false }); }
    catch (e) { console.warn("maps-place start failed", e); }
    finally { setTimeout(() => setMapsPlaceStarting(false), 800); }
  };

  return (
    <div data-testid="audit-batch-hub" data-mode-card="marinas">
      <CardShell title={t("modeMarinas")} icon={<Anchor size={13} className="text-alert" />} borderCls="border-alert/40">
        <div>
          <label className="font-mono text-[9px] uppercase tracking-widest text-slate-500 block mb-1">
            {t("auditMarinasBuild")}
          </label>
          <p className="mb-2 text-[10px] font-mono text-slate-500 leading-relaxed">
            {t("auditMarinasWorldHint")}
          </p>
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
              ✓ +{buildStatus.summary.inserted ?? 0} · ~{buildStatus.summary.updated ?? 0} · OSM {buildStatus.summary.fetched_raw ?? 0}
            </p>
          )}
          <button
            data-testid="audit-maps-place-btn"
            onClick={startMapsPlace}
            disabled={mapsPlaceStarting || mapsPlaceStatus?.running}
            className="mt-2 w-full flex items-center justify-center gap-2 px-3 py-2 border border-alert/40 bg-alert/10 hover:bg-alert/20 disabled:opacity-70 disabled:cursor-not-allowed text-alert font-semibold text-xs rounded-sm"
          >
            {mapsPlaceStatus?.running ? (
              <><Loader2 size={13} className="animate-spin" /> {mapsPlaceStatus.progress}/{mapsPlaceStatus.total}</>
            ) : (
              <><PlayCircle size={13} /> {t("auditMapsPlace")}</>
            )}
          </button>
          {mapsPlaceStatus?.summary && !mapsPlaceStatus.running && (
            <p className="mt-1.5 text-[9px] font-mono text-slate-500 leading-relaxed">
              ✓ /place/ {mapsPlaceStatus.summary.found ?? 0} · none {mapsPlaceStatus.summary.none ?? 0}
            </p>
          )}
          {/* Phase 8 — anchorages scan (same ±25 NM corridor logic) */}
          <label className="flex items-center gap-2 mt-3 mb-2 text-xs text-slate-400 cursor-pointer select-none">
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
