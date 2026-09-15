import { X } from "lucide-react";
import { useState } from "react";

export default function ReportPoEModal({ t, onClose, onSubmit }) {
  const [formData, setFormData] = useState({
    eezName: "",
    portName: "",
    officialUrl: "",
    notes: ""
  });
  const [error, setError] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!formData.eezName.trim() || !formData.portName.trim() || !formData.officialUrl.trim()) {
      setError(t("reportPoEErrorEmpty") || "Please fill all required fields.");
      return;
    }
    if (!formData.officialUrl.startsWith("http")) {
      setError(t("reportPoEErrorUrl") || "URL must start with http.");
      return;
    }
    setError("");
    onSubmit(formData);
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-md bg-surface border border-line rounded-sm shadow-2xl flex flex-col">
        <div className="flex items-center justify-between p-4 border-b border-line">
          <h2 className="font-heading font-bold text-white text-lg">{t("reportPoETitle") || "Suggest a Port of Entry"}</h2>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-white rounded-sm hover:bg-raised transition-colors">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 flex flex-col gap-4">
          {error && <div className="p-2 bg-alert/10 text-alert border border-alert/40 text-xs rounded-sm">{error}</div>}
          
          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">{t("reportPoEEez") || "Country or EEZ name *"}</span>
            <input type="text" required value={formData.eezName} onChange={(e) => setFormData({...formData, eezName: e.target.value})} className="bg-raised border border-line rounded-sm px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-amberx" />
          </label>
          
          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">{t("reportPoEName") || "Port name *"}</span>
            <input type="text" required value={formData.portName} onChange={(e) => setFormData({...formData, portName: e.target.value})} className="bg-raised border border-line rounded-sm px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-amberx" />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">{t("reportPoEUrl") || "Official URL (must start with http) *"}</span>
            <input type="url" required value={formData.officialUrl} onChange={(e) => setFormData({...formData, officialUrl: e.target.value})} placeholder="https://..." className="bg-raised border border-line rounded-sm px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-amberx" />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-widest text-slate-400">{t("reportPoENotes") || "Optional short note"}</span>
            <textarea value={formData.notes} onChange={(e) => setFormData({...formData, notes: e.target.value})} rows={2} className="bg-raised border border-line rounded-sm px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-amberx resize-none" />
          </label>

          <div className="pt-2 flex justify-end gap-3">
            <button type="button" onClick={onClose} className="px-4 py-2 text-xs font-semibold text-slate-300 hover:text-white transition-colors">{t("cancel") || "Cancel"}</button>
            <button type="submit" className="px-4 py-2 text-xs font-semibold bg-amberx text-black rounded-sm hover:bg-amberx/90 transition-colors">{t("submit") || "Submit"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}