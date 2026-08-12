import { useState } from "react";
import { Flag, Loader2, X } from "lucide-react";
import api from "../api";

const inputCls = "w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500";

export default function ReportModal({ t, onClose }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);

  const submit = async () => {
    if (!name.trim() || !url.trim().startsWith("http")) {
      alert(t("reportInvalid"));
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/report-project", { name, url, description: desc });
      setDone(data);
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/70 backdrop-blur-sm" data-testid="report-modal">
      <div className="w-[400px] bg-surface border border-line rounded-sm p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-heading font-bold text-base text-white flex items-center gap-2">
            <Flag size={15} className="text-sonar" /> {t("reportTitle")}
          </h3>
          <button data-testid="report-close-btn" onClick={onClose} className="text-slate-500 hover:text-slate-200"><X size={15} /></button>
        </div>
        {done ? (
          <div className="text-center py-4" data-testid="report-success">
            <p className="font-heading font-bold text-bio mb-2">{t("reportThanks")}</p>
            <p className="text-xs text-slate-400 mb-1">
              {done.status === "queued_now" ? t("reportQueuedNow") : t("reportQueuedNext")}
            </p>
            <p className="font-mono text-[10px] text-slate-500">
              Email: {done.email_status === "sent" ? "✓ " + t("reportEmailSent") : done.email_status}
            </p>
            <button data-testid="report-done-btn" onClick={onClose}
              className="mt-4 px-4 py-2 text-xs font-semibold border border-sonar/50 text-sonar rounded-sm hover:bg-sonar/10">
              OK
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <label className="block font-mono text-[10px] uppercase text-slate-500 mb-1">{t("reportName")} *</label>
              <input data-testid="report-name-input" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Coral Gardeners Moorea…" className={inputCls} />
            </div>
            <div>
              <label className="block font-mono text-[10px] uppercase text-slate-500 mb-1">URL *</label>
              <input data-testid="report-url-input" value={url} onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…" className={inputCls} />
            </div>
            <div>
              <label className="block font-mono text-[10px] uppercase text-slate-500 mb-1">{t("reportDesc")}</label>
              <textarea data-testid="report-desc-input" value={desc} onChange={(e) => setDesc(e.target.value)}
                rows={3} className={inputCls} />
            </div>
            <button data-testid="report-submit-btn" onClick={submit} disabled={busy}
              className="w-full flex items-center justify-center gap-2 py-2 font-heading font-bold text-sm rounded-sm bg-sonar/15 border border-sonar/60 text-sonar hover:bg-sonar/25 disabled:opacity-40">
              {busy ? <Loader2 size={14} className="animate-spin" /> : <Flag size={13} />} {t("reportSubmit")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
