import { useCallback, useEffect, useState } from "react";
import { Check, Download, RefreshCw, ThumbsDown, ThumbsUp, Upload } from "lucide-react";
import api from "../../api";
import CardShell, { smallInput } from "./CardShell";

const FILTERS = [
  ["pending", "reviewFilterPending"],
  ["v1_snapped", "reviewSrcSnapped"],
  ["v1_fallback", "reviewSrcFallback"],
  ["run_unlocated", "reviewSrcUnlocated"],
  ["run_hq", "reviewSrcHq"],
  ["run_diff", "reviewSrcDiff"],
  ["accepted", "reviewFilterAccepted"],
  ["rejected", "reviewFilterRejected"],
];

function isStatusFilter(key) {
  return key === "pending" || key === "accepted" || key === "rejected";
}

/**
 * ReviewCard — file opérateur phase D : snapped / fallback / HQ / unlocated,
 * accepter ou rejeter un site, promouvoir un run, exporter le Gold, ré-entraîner.
 */
export default function ReviewCard({ t, status }) {
  const [stats, setStats] = useState(null);
  const [gold, setGold] = useState(null);
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("pending");
  const [drafts, setDrafts] = useState({});
  const [busy, setBusy] = useState(false);
  const [runs, setRuns] = useState([]);
  const [promoteId, setPromoteId] = useState("");
  const [trainLog, setTrainLog] = useState(null);
  const [msg, setMsg] = useState(null);

  const load = useCallback(async () => {
    try {
      const params = isStatusFilter(filter)
        ? { status: filter, limit: 80 }
        : { status: "pending", source: filter, limit: 80 };
      const [st, g, list, rs] = await Promise.all([
        api.get("/projects/review/stats"),
        api.get("/projects/gold"),
        api.get("/projects/review", { params }),
        api.get("/projects/runs"),
      ]);
      setStats(st.data);
      setGold(g.data);
      setItems(list.data.items || []);
      const runItems = rs.data.items || [];
      setRuns(runItems);
      if (!promoteId && runItems[0]?._id) setPromoteId(runItems[0]._id);
    } catch (e) {
      setMsg(e.response?.data?.detail || e.message);
    }
  }, [filter, promoteId]);

  useEffect(() => { load(); }, [load]);

  const setDraft = (id, patch) => {
    setDrafts((d) => ({ ...d, [id]: { ...(d[id] || {}), ...patch } }));
  };
  const draftOf = (it) => drafts[it.id] || {};

  const act = async (fn) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setMsg(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const rebuild = () => act(() => api.post("/projects/review/rebuild", {
    run_id: promoteId || undefined,
  }));

  const accept = (it) => act(async () => {
    const d = draftOf(it);
    const lat = d.lat !== undefined && d.lat !== "" ? parseFloat(d.lat) : it.lat;
    const lon = d.lon !== undefined && d.lon !== "" ? parseFloat(d.lon) : it.lon;
    await api.post(`/projects/review/${encodeURIComponent(it.id)}/accept`, {
      lat: Number.isFinite(lat) ? lat : null,
      lon: Number.isFinite(lon) ? lon : null,
      site_name: d.site_name || it.edited_site_name || it.location || undefined,
    });
  });

  const reject = (it) => act(() =>
    api.post(`/projects/review/${encodeURIComponent(it.id)}/reject`, {
      note: draftOf(it).note || "",
    }));

  const promote = () => {
    if (!promoteId) return;
    if (!window.confirm(t("reviewPromoteConfirm"))) return;
    act(() => api.post(`/projects/runs/${promoteId}/promote`));
  };

  const exportGold = () => act(async () => {
    const { data } = await api.post("/projects/gold/export");
    setGold(data);
    setMsg(t("reviewGoldExported").replace("{n}", String(data.exported ?? data.gold_count ?? 0)));
  });

  const retrain = () => act(async () => {
    await api.post("/ml/train/gatekeeper");
    setTrainLog({ running: true });
    for (let i = 0; i < 40; i += 1) {
      await new Promise((r) => setTimeout(r, 800));
      const { data } = await api.get("/ml/train/status");
      setTrainLog(data);
      if (!data.running) break;
    }
  });

  const pending = stats?.by_status?.pending ?? 0;
  const runId = status?.run_id;

  return (
    <div data-testid="project-review-card">
      <CardShell title={t("reviewTitle")} borderCls="border-sonar/40">
        <p className="font-mono text-[9px] text-slate-500 leading-relaxed">
          {t("reviewHint")}
        </p>

        <div className="grid grid-cols-3 gap-px bg-line border border-line">
          <div className="bg-surface p-2">
            <p className="font-mono text-[9px] text-slate-500 uppercase">{t("reviewPending")}</p>
            <p data-testid="review-pending-count" className="font-heading font-black text-lg text-amberx">{pending}</p>
          </div>
          <div className="bg-surface p-2">
            <p className="font-mono text-[9px] text-slate-500 uppercase">{t("reviewGold")}</p>
            <p data-testid="review-gold-count" className="font-heading font-black text-lg text-bio">{gold?.gold_count ?? "—"}</p>
          </div>
          <div className="bg-surface p-2">
            <p className="font-mono text-[9px] text-slate-500 uppercase">{t("reviewAccepted")}</p>
            <p className="font-heading font-black text-lg text-sonar">{stats?.by_status?.accepted ?? 0}</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-1" data-testid="review-filters">
          {FILTERS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              data-testid={`review-filter-${key}`}
              onClick={() => setFilter(key)}
              className={`px-1.5 py-0.5 font-mono text-[9px] uppercase rounded-sm border ${
                filter === key
                  ? "border-sonar/50 bg-sonar/10 text-sonar"
                  : "border-line text-slate-500 hover:bg-raised"
              }`}
            >
              {t(label)}
              {key === "pending" ? ` ${pending}` : ""}
            </button>
          ))}
        </div>

        <div className="flex gap-2">
          <button
            type="button"
            data-testid="review-rebuild-btn"
            onClick={rebuild}
            disabled={busy}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-[11px] font-semibold rounded-sm border border-line text-slate-300 hover:bg-raised disabled:opacity-40"
          >
            <RefreshCw size={11} /> {t("reviewRebuild")}
          </button>
          <button
            type="button"
            data-testid="review-gold-export-btn"
            onClick={exportGold}
            disabled={busy}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 text-[11px] font-semibold rounded-sm border border-bio/50 text-bio hover:bg-bio/10 disabled:opacity-40"
          >
            <Download size={11} /> {t("reviewExportGold")}
          </button>
        </div>

        <button
          type="button"
          data-testid="review-retrain-btn"
          onClick={retrain}
          disabled={busy}
          className="w-full flex items-center justify-center gap-1.5 py-1.5 text-[11px] font-semibold rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25 disabled:opacity-40"
        >
          <Upload size={11} /> {t("reviewRetrain")}
        </button>
        {trainLog && (
          <p className="font-mono text-[9px] text-slate-400" data-testid="review-train-status">
            {trainLog.running ? t("reviewTraining") : (trainLog.summary
              ? `n_pos=${trainLog.summary.n_pos} f1=${trainLog.summary.f1}`
              : (trainLog.error || t("reviewTrainIdle")))}
          </p>
        )}

        <div className="pt-2 border-t border-line space-y-2">
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-sonar/80">{t("reviewPromote")}</p>
          <select
            data-testid="review-promote-run"
            value={promoteId}
            onChange={(e) => setPromoteId(e.target.value)}
            className={smallInput}
          >
            <option value="">{t("reviewPickRun")}</option>
            {runs.map((r) => (
              <option key={r._id} value={r._id}>
                {r._id} · {r.state}{r.wrote_projects ? " · carte" : ""}
              </option>
            ))}
          </select>
          {runId && (
            <p className="font-mono text-[9px] text-slate-500">{t("currentRun")} {runId}</p>
          )}
          <button
            type="button"
            data-testid="review-promote-btn"
            onClick={promote}
            disabled={busy || !promoteId}
            className="w-full flex items-center justify-center gap-1.5 py-1.5 text-[11px] font-semibold rounded-sm border border-amberx/50 text-amberx hover:bg-amberx/10 disabled:opacity-40"
          >
            {t("reviewPromoteBtn")}
          </button>
        </div>

        {msg && (
          <p className="font-mono text-[10px] text-amberx" data-testid="review-msg">{msg}</p>
        )}

        <div className="divide-y divide-line/50 border border-line/60 rounded-sm max-h-[420px] overflow-y-auto" data-testid="review-queue">
          {items.length === 0 && (
            <p className="p-2 text-[11px] text-slate-500">{t("reviewEmpty")}</p>
          )}
          {items.map((it) => {
            const d = draftOf(it);
            return (
              <div key={it.id} className="p-2 space-y-1.5" data-testid={`review-item-${it.id}`}>
                <div className="flex items-start justify-between gap-2">
                  <p className="text-[11px] font-semibold text-slate-200 leading-snug">{it.title || it.url}</p>
                  <span className="shrink-0 font-mono text-[9px] uppercase text-amberx">{it.source}</span>
                </div>
                <p className="font-mono text-[9px] text-slate-500 truncate" title={it.url}>{it.url}</p>
                {it.reason && <p className="text-[10px] text-slate-500">{it.reason}</p>}
                {it.status === "pending" && (
                  <>
                    <div className="grid grid-cols-2 gap-1">
                      <input
                        data-testid={`review-lat-${it.id}`}
                        className={smallInput}
                        placeholder="lat"
                        value={d.lat ?? (it.lat ?? "")}
                        onChange={(e) => setDraft(it.id, { lat: e.target.value })}
                      />
                      <input
                        data-testid={`review-lon-${it.id}`}
                        className={smallInput}
                        placeholder="lon"
                        value={d.lon ?? (it.lon ?? "")}
                        onChange={(e) => setDraft(it.id, { lon: e.target.value })}
                      />
                    </div>
                    <input
                      className={smallInput}
                      placeholder={t("reviewSiteName")}
                      value={d.site_name ?? it.edited_site_name ?? it.location ?? ""}
                      onChange={(e) => setDraft(it.id, { site_name: e.target.value })}
                    />
                    <div className="flex gap-1">
                      <button
                        type="button"
                        data-testid={`review-accept-${it.id}`}
                        onClick={() => accept(it)}
                        disabled={busy}
                        className="flex-1 flex items-center justify-center gap-1 py-1 text-[10px] font-semibold rounded-sm border border-bio/50 text-bio hover:bg-bio/10 disabled:opacity-40"
                      >
                        <ThumbsUp size={10} /> {t("reviewAccept")}
                      </button>
                      <button
                        type="button"
                        data-testid={`review-reject-${it.id}`}
                        onClick={() => reject(it)}
                        disabled={busy}
                        className="flex-1 flex items-center justify-center gap-1 py-1 text-[10px] font-semibold rounded-sm border border-alert/50 text-alert hover:bg-alert/10 disabled:opacity-40"
                      >
                        <ThumbsDown size={10} /> {t("reviewReject")}
                      </button>
                    </div>
                  </>
                )}
                {it.status !== "pending" && (
                  <p className="font-mono text-[9px] text-slate-400 flex items-center gap-1">
                    <Check size={10} /> {it.status}
                    {it.lat != null && ` · ${it.lat}, ${it.lon}`}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </CardShell>
    </div>
  );
}
