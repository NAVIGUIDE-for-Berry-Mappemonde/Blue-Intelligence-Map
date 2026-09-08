import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ClipboardCheck, Search } from "lucide-react";
import api from "../api";
import ZoneFiche from "./ZoneFiche";
import ProjectFiche from "./review/ProjectFiche";
import MarinaFiche from "./review/MarinaFiche";

const PAGE = 500;

function kindFromMode(mode) {
  if (mode === "marinas") return "marina";
  if (mode === "formalities") return "eez";
  return "project";
}

function kindLabelKey(kind) {
  if (kind === "eez") return "reviewKindEez";
  if (kind === "marina") return "reviewKindMarina";
  return "reviewKindProject";
}

export default function ReviewView({ t, mode, onMapDirty }) {
  const kind = kindFromMode(mode);
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("published");
  const [queue, setQueue] = useState([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState("");
  const [q, setQ] = useState("");
  const [preGold, setPreGold] = useState(true);
  const [stableOnly, setStableOnly] = useState(kind === "eez");
  const [index, setIndex] = useState(0);
  const [fiche, setFiche] = useState(null);
  const [loading, setLoading] = useState(false);
  const [queueLoading, setQueueLoading] = useState(true);
  const [comment, setComment] = useState("");
  const [savedAt, setSavedAt] = useState(null);
  const [saving, setSaving] = useState(false);
  const [goldOn, setGoldOn] = useState(false);
  const [goldBusy, setGoldBusy] = useState(false);
  const dirtyRef = useRef(false);
  const commentRef = useRef("");
  const currentIdRef = useRef(null);
  const pendingIndexRef = useRef(0);

  useEffect(() => {
    setIndex(0);
    setOffset(0);
    setFilter("");
    setQ("");
    setPreGold(true);
    setStableOnly(kindFromMode(mode) === "eez");
    if (mode === "formalities") setRunId("published");
  }, [mode]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(filter.trim());
      setOffset(0);
      pendingIndexRef.current = 0;
    }, 250);
    return () => clearTimeout(timer);
  }, [filter]);

  const current = queue[index] || null;
  const effectiveRunId = kind === "eez" ? "published" : runId;

  const persistIfDirty = useCallback(async () => {
    const id = currentIdRef.current;
    if (!dirtyRef.current || !id) return;
    try {
      setSaving(true);
      const { data } = await api.put("/review/comment", {
        kind, run_id: effectiveRunId, id, comment: commentRef.current,
      });
      dirtyRef.current = false;
      setSavedAt(data.updated_at || new Date().toISOString());
      setQueue((items) => items.map((it) => (
        it.id === id ? { ...it, has_comment: Boolean((commentRef.current || "").trim()) } : it
      )));
    } catch (e) {
      /* transient */
    } finally {
      setSaving(false);
    }
  }, [kind, effectiveRunId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get("/review/runs", { params: { kind } });
        if (cancelled) return;
        const items = data.items || [];
        setRuns(items);
        const rec = items.find((r) => r.recommended);
        if (kind === "eez" && rec) {
          setRunId(rec.id);
        } else {
          setRunId((prev) => (items.some((r) => r.id === prev) ? prev : "published"));
        }
      } catch (e) {
        if (!cancelled) setRuns([{ id: "published", label: "published", count: 0 }]);
      }
    })();
    return () => { cancelled = true; };
  }, [kind]);

  useEffect(() => {
    let cancelled = false;
    setQueueLoading(true);
    (async () => {
      try {
        const { data } = await api.get("/review/queue", {
          params: {
            kind, run_id: effectiveRunId, offset, limit: PAGE, q,
            pre_gold: preGold, stable: kind === "eez" && stableOnly,
          },
        });
        if (cancelled) return;
        const items = data.items || [];
        setQueue(items);
        setTotal(data.total || 0);
        const want = pendingIndexRef.current;
        pendingIndexRef.current = 0;
        setIndex(items.length ? Math.min(Math.max(want, 0), items.length - 1) : 0);
      } catch (e) {
        if (!cancelled) {
          setQueue([]);
          setTotal(0);
        }
      } finally {
        if (!cancelled) setQueueLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [kind, effectiveRunId, offset, q, preGold, stableOnly]);

  useEffect(() => {
    setFiche(null);
    setComment("");
    setSavedAt(null);
    setGoldOn(false);
  }, [kind, effectiveRunId, preGold, stableOnly]);

  useEffect(() => {
    commentRef.current = comment;
  }, [comment]);

  useEffect(() => {
    currentIdRef.current = current?.id || null;
    if (!current) {
      setFiche(null);
      setComment("");
      setSavedAt(null);
      setGoldOn(false);
      dirtyRef.current = false;
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const params = { kind, run_id: effectiveRunId, id: current.id };
        if (
          current.source_run_id
          && current.source_run_id !== effectiveRunId
          && effectiveRunId !== "published"
        ) {
          params.content_run_id = current.source_run_id;
        }
        const { data } = await api.get("/review/fiche", { params });
        if (cancelled) return;
        setFiche(data.fiche);
        setComment(data.comment || "");
        setSavedAt(data.comment_updated_at || null);
        setGoldOn(Boolean(data.gold_on));
        dirtyRef.current = false;
      } catch (e) {
        if (!cancelled) setFiche(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [kind, effectiveRunId, current?.id, current?.source_run_id]);

  const go = useCallback(async (delta) => {
    if (!total) return;
    await persistIfDirty();
    const next = index + delta;
    if (next >= 0 && next < queue.length) {
      setIndex(next);
      return;
    }
    if (next >= queue.length) {
      const nextOff = offset + queue.length;
      if (nextOff < total) {
        pendingIndexRef.current = 0;
        setOffset(nextOff);
      } else {
        pendingIndexRef.current = 0;
        setOffset(0);
      }
      return;
    }
    if (offset > 0) {
      const prevOff = Math.max(0, offset - PAGE);
      pendingIndexRef.current = PAGE - 1;
      setOffset(prevOff);
      return;
    }
    const lastOff = Math.max(0, Math.floor((total - 1) / PAGE) * PAGE);
    pendingIndexRef.current = Math.max(0, (total - lastOff) - 1);
    setOffset(lastOff);
  }, [total, index, queue.length, offset, persistIfDirty]);

  useEffect(() => {
    const onKey = (e) => {
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "TEXTAREA" || e.target?.tagName === "INPUT" || tag === "SELECT") return;
      if (e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
      if (e.key === "ArrowRight") { e.preventDefault(); go(1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  const saveComment = async () => {
    if (!current) return;
    try {
      setSaving(true);
      const { data } = await api.put("/review/comment", {
        kind, run_id: effectiveRunId, id: current.id, comment,
      });
      dirtyRef.current = false;
      setSavedAt(data.updated_at || new Date().toISOString());
      setQueue((items) => items.map((it) => (
        it.id === current.id ? { ...it, has_comment: Boolean((comment || "").trim()) } : it
      )));
    } catch (e) {
      /* transient */
    } finally {
      setSaving(false);
    }
  };

  const toggleGold = async () => {
    if (!current || goldBusy) return;
    try {
      setGoldBusy(true);
      const { data } = await api.put("/review/gold", {
        kind, run_id: effectiveRunId, id: current.id,
      });
      const pressed = Boolean(data.gold_on);
      setGoldOn(pressed);
      setQueue((items) => items.map((it) => (
        it.id === current.id ? { ...it, gold_on: pressed } : it
      )));
      if (onMapDirty) onMapDirty();
    } catch (e) {
      /* transient */
    } finally {
      setGoldBusy(false);
    }
  };

  const renderFiche = () => {
    if (!fiche) {
      return (
        <p className="p-8 font-mono text-sm text-slate-400" data-testid="review-fiche-loading">
          {loading ? t("poeFicheLoading") : t("reviewEmpty")}
        </p>
      );
    }
    if (kind === "eez") return <ZoneFiche t={t} fiche={fiche} variant="page" />;
    if (kind === "project") return <ProjectFiche t={t} fiche={fiche} />;
    return <MarinaFiche t={t} fiche={fiche} />;
  };

  return (
    <div className="h-full flex min-h-0 bg-abyss" data-testid="review-view" data-review-kind={kind}>
      <aside className="w-[280px] shrink-0 flex flex-col border-r border-line bg-surface">
        <div className="p-3 border-b border-line">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 mb-2">
            {t("reviewJump")} <span className="text-accent">({total})</span>
          </p>
          <div className="relative">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              data-testid="review-search-input"
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder={t("reviewSearch")}
              className="w-full bg-raised border border-line rounded-sm pl-7 pr-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent/50"
            />
          </div>
          <button
            type="button"
            data-testid="review-pregold-filter"
            aria-pressed={preGold}
            onClick={() => { setPreGold((v) => !v); setOffset(0); pendingIndexRef.current = 0; }}
            className={`mt-2 w-full px-2.5 py-1.5 text-[11px] font-semibold border rounded-sm ${
              preGold
                ? "border-accent/50 bg-accent/15 text-accent"
                : "border-line text-slate-400 hover:text-slate-200 hover:bg-raised"
            }`}
          >
            {t("reviewPreGold")}
          </button>
          {kind === "eez" && (
            <button
              type="button"
              data-testid="review-stable-filter"
              aria-pressed={stableOnly}
              onClick={() => { setStableOnly((v) => !v); setOffset(0); pendingIndexRef.current = 0; }}
              className={`mt-2 w-full px-2.5 py-1.5 text-[11px] font-semibold border rounded-sm ${
                stableOnly
                  ? "border-accent/50 bg-accent/15 text-accent"
                  : "border-line text-slate-400 hover:text-slate-200 hover:bg-raised"
              }`}
            >
              {t("reviewStable")}
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto" data-testid="review-queue-list">
          {queue.length === 0 && (
            <p className="p-4 text-xs text-slate-500">
              {queueLoading ? t("reviewQueueLoading") : t("reviewEmpty")}
            </p>
          )}
          {queue.map((it, i) => (
            <button
              key={it.id}
              type="button"
              data-testid={`review-queue-item-${it.id}`}
              onClick={async () => { await persistIfDirty(); setIndex(i); }}
              className={`w-full text-left px-3 py-2 border-b border-line hover:bg-raised transition-colors ${
                i === index ? "bg-accent/10 border-l-2 border-l-accent" : ""
              }`}
            >
              <div className="flex items-start gap-2">
                <span className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${
                  it.has_comment ? "bg-bio" : "bg-slate-600"
                }`} title={it.has_comment ? t("reviewHasComment") : undefined} />
                <div className="min-w-0">
                  <p className="text-xs text-slate-100 truncate">
                    {it.title}
                    {it.stable ? (
                      <span className="ml-1 font-mono text-[9px] text-accent/80" data-testid="review-stable-badge">
                        11
                      </span>
                    ) : null}
                  </p>
                  {it.subtitle ? (
                    <p className="font-mono text-[10px] text-slate-500 truncate">{it.subtitle}</p>
                  ) : null}
                </div>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <div className="px-5 py-3 border-b border-line flex flex-wrap items-center gap-2">
          <ClipboardCheck size={16} className="text-accent" />
          <h2 className="font-heading font-black text-lg text-accent mr-2">
            {t("reviewTitle")}
            <span className="ml-2 font-semibold text-sm text-slate-300" data-testid="review-mode-label">
              {t(kindLabelKey(kind))}
            </span>
          </h2>
          {kind === "project" && (
            <select
              data-testid="review-run-select"
              value={runId}
              onChange={async (e) => { await persistIfDirty(); setRunId(e.target.value); setOffset(0); pendingIndexRef.current = 0; }}
              className="bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent/50 max-w-[280px]"
            >
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.id === "published" ? t("reviewPublished") : (r.label || r.id)}
                  {r.count != null ? ` (${r.count})` : ""}
                  {r.recommended ? ` · ${t("reviewRecommended")}` : ""}
                </option>
              ))}
            </select>
          )}
          <span className="ml-auto font-mono text-[11px] text-slate-400" data-testid="review-counter">
            {total ? `${offset + index + 1} / ${total}` : "0 / 0"}
          </span>
          <button
            type="button"
            data-testid="review-prev"
            onClick={() => go(-1)}
            disabled={!total}
            className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-semibold border border-line rounded-sm text-slate-300 hover:bg-raised disabled:opacity-40"
          >
            <ChevronLeft size={13} /> {t("reviewPrev")}
          </button>
          <button
            type="button"
            data-testid="review-next"
            onClick={() => go(1)}
            disabled={!total}
            className="flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-semibold border border-line rounded-sm text-slate-300 hover:bg-raised disabled:opacity-40"
          >
            {t("reviewNext")} <ChevronRight size={13} />
          </button>
        </div>
        <p className="px-5 py-2 font-mono text-[10px] text-slate-500 border-b border-line" data-testid="review-hint">
          {t(kind === "eez" ? "reviewHintFormalities" : "reviewHint")}
        </p>
        <div className="flex-1 overflow-y-auto" data-testid="review-fiche-pane">
          {queue.length === 0 && !loading ? (
            <p className="p-6 text-sm text-slate-500">
              {queueLoading ? t("reviewQueueLoading") : t("reviewEmpty")}
            </p>
          ) : renderFiche()}
        </div>
        <div className="border-t border-line p-4 bg-surface space-y-2" data-testid="review-comment-box">
          <div className="flex items-center justify-between">
            <label htmlFor="review-comment" className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
              {t("reviewComment")}
            </label>
            {savedAt && (
              <span className="font-mono text-[10px] text-bio" data-testid="review-comment-saved">
                {saving ? t("reviewSaving") : t("reviewSaved")}
              </span>
            )}
          </div>
          <textarea
            id="review-comment"
            data-testid="review-comment"
            value={comment}
            disabled={!current}
            onChange={(e) => { setComment(e.target.value); dirtyRef.current = true; }}
            placeholder={t("reviewCommentPlaceholder")}
            rows={4}
            className="w-full bg-raised border border-line rounded-sm px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent/50 disabled:opacity-40"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="review-comment-save"
              onClick={saveComment}
              disabled={!current || saving}
              className="px-3 py-1.5 text-[11px] font-semibold border border-accent/50 text-accent rounded-sm hover:bg-accent/10 disabled:opacity-40"
            >
              {saving ? t("reviewSaving") : t("reviewSave")}
            </button>
            <button
              type="button"
              data-testid="review-gold"
              aria-pressed={goldOn}
              onClick={toggleGold}
              disabled={!current || goldBusy}
              className={`px-3 py-1.5 text-[11px] font-semibold border rounded-sm disabled:opacity-40 ${
                goldOn
                  ? "border-accent bg-accent/20 text-accent"
                  : "border-line text-slate-300 hover:bg-raised"
              }`}
            >
              {t("reviewGold")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
