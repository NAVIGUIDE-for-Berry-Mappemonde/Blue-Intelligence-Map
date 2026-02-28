/**
 * NAVIGUIDE — Polar Sidebar (right panel)
 * ─────────────────────────────────────────────────────
 * Upload zone (auto-upload on file select/drop) + VMG table.
 * Chat has moved to the left Sidebar above Briefing.
 *
 * Props:
 *   open            {boolean}   panel visibility
 *   onToggle        {fn}        toggle open/close
 *   exportOpen      {boolean}   whether ExportSidebar is open
 *   polarData       {object}    shared polar state from App
 *   onPolarDataLoaded {fn}      callback to lift polar data to App
 */

import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft, ChevronRight, Upload,
  Compass, TriangleAlert, CheckCircle2, Loader2,
} from "lucide-react";

const POLAR_API_URL = import.meta.env.VITE_POLAR_API_URL ?? "http://localhost:8004";
const DEFAULT_EXPEDITION_ID = "berry-mappemonde-2026";

const VMG_TWS_KEYS = ["8", "10", "12", "16", "20", "25"];

function kts(v) { return v != null ? `${Number(v).toFixed(1)} kt` : "—"; }
function deg(v) { return v != null ? `${Math.round(v)}°` : "—"; }

function StatusBadge({ status, detail }) {
  const cfg = {
    uploading: { icon: <Loader2 size={13} className="animate-spin" />, color: "text-blue-400",  bg: "bg-blue-900/30",  text: "Analyse…" },
    success:   { icon: <CheckCircle2 size={13} />,                     color: "text-green-400", bg: "bg-green-900/30", text: "Polaires chargées" },
    error:     { icon: <TriangleAlert size={13} />,                    color: "text-red-400",   bg: "bg-red-900/30",   text: "Échec" },
  };
  if (!status) return null;
  const c = cfg[status] ?? cfg.error;
  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg ${c.bg} ${c.color} text-xs mt-2`}>
      {c.icon}
      <span className="font-medium">{c.text}</span>
      {detail && <span className="text-slate-400 truncate ml-1">— {detail}</span>}
    </div>
  );
}

function VmgRow({ tws, entry }) {
  const uw = entry?.upwind   ?? {};
  const dw = entry?.downwind ?? {};
  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/40 transition-colors">
      <td className="py-1.5 pl-2 pr-1 text-center font-bold text-blue-300 text-xs w-10">{tws}</td>
      <td className="py-1.5 px-1 text-center text-xs text-green-300">{deg(uw.twa)}</td>
      <td className="py-1.5 px-1 text-center text-xs text-slate-200">{kts(uw.speed)}</td>
      <td className="py-1.5 px-1 text-center text-xs font-semibold text-green-400">{kts(uw.vmg)}</td>
      <td className="py-1.5 px-0.5 text-slate-600 text-center text-xs">│</td>
      <td className="py-1.5 px-1 text-center text-xs text-amber-300">{deg(dw.twa)}</td>
      <td className="py-1.5 px-1 text-center text-xs text-slate-200">{kts(dw.speed)}</td>
      <td className="py-1.5 pr-2 pl-1 text-center text-xs font-semibold text-amber-400">{kts(dw.vmg)}</td>
    </tr>
  );
}

export function PolarSidebar({ open, onToggle, exportOpen, polarData, onPolarDataLoaded }) {
  const [file,         setFile]         = useState(null);
  const [uploadStatus, setUploadStatus] = useState(null);
  const [uploadDetail, setUploadDetail] = useState("");
  const [isDragging,   setIsDragging]   = useState(false);
  const fileInputRef                    = useRef(null);

  /* Auto-upload whenever a file is selected */
  useEffect(() => {
    if (file) handleUpload(file);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  const handleUpload = async (f) => {
    setUploadStatus("uploading");
    setUploadDetail("");
    const form = new FormData();
    form.append("file",          f);
    form.append("expedition_id", DEFAULT_EXPEDITION_ID);
    try {
      const res  = await fetch(`${POLAR_API_URL}/api/v1/polar/upload`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);
      onPolarDataLoaded({
        expedition_id: data.expedition_id,
        boat_name:     data.boat_name,
        grid_shape:    data.grid_shape,
        vmg_summary:   data.vmg_summary,
        created_at:    data.created_at,
      });
      setUploadStatus("success");
      setUploadDetail(data.boat_name);
    } catch (err) {
      setUploadStatus("error");
      setUploadDetail(String(err.message ?? err));
    }
  };

  /* Drag handlers */
  const handleDragOver  = (e) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = ()  => setIsDragging(false);
  const handleDrop      = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files?.[0];
    const allowed = [".pdf", ".csv", ".xlsx", ".xls"];
    if (f && allowed.some(ext => f.name.toLowerCase().endsWith(ext))) setFile(f);
  };

  const toggleRight = open
    ? exportOpen ? "right-[648px]" : "right-[326px]"
    : exportOpen ? "right-[326px]" : "right-4";

  const panelRight = exportOpen ? "320px" : "0px";

  return (
    <>
      {/* Toggle button */}
      <button
        onClick={onToggle}
        className={`naviguide-sidebar-toggle absolute top-16 z-30 bg-slate-900/95 border border-slate-700
          text-white rounded-full w-9 h-9 flex items-center justify-center shadow-lg
          hover:bg-slate-800 transition-all duration-300 ${toggleRight}`}
        title={open ? "Masquer polaires" : "Afficher polaires"}
      >
        {open ? <ChevronRight size={16} /> : <Compass size={16} className="text-blue-400" />}
      </button>

      {/* Panel */}
      <div
        className={`naviguide-sidebar-panel absolute top-0 h-full z-20 flex flex-col bg-slate-900/97
          border-l border-slate-700/60 shadow-2xl transition-all duration-300
          ${open ? "translate-x-0 opacity-100" : "translate-x-full opacity-0"}`}
        style={{ width: 320, right: panelRight }}
      >
        {/* Header */}
        <div className="px-4 pt-4 pb-3 border-b border-slate-700/60 flex-shrink-0">
          <div className="flex items-center gap-2">
            <Compass size={16} className="text-blue-400 flex-shrink-0" />
            <span className="text-sm font-bold text-white">Polaires</span>
            {polarData && (
              <span className="ml-auto text-xs text-green-400 bg-green-900/30 px-2 py-0.5 rounded-full font-medium">
                {polarData.boat_name}
              </span>
            )}
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto sidebar-scroll px-4 py-4 space-y-4">

          {/* Drop zone */}
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`relative flex flex-col items-center justify-center gap-2 p-6
              border-2 border-dashed rounded-xl cursor-pointer transition-colors
              ${isDragging
                ? "border-blue-400 bg-blue-900/20"
                : uploadStatus === "success"
                  ? "border-green-500/60 bg-green-900/10"
                  : uploadStatus === "uploading"
                    ? "border-blue-500/40 bg-blue-900/10"
                    : "border-slate-600 hover:border-slate-500 bg-slate-800/40"}`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.csv,.xlsx,.xls"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); }}
            />
            {uploadStatus === "uploading"
              ? <Loader2 size={20} className="animate-spin text-blue-400" />
              : <Upload size={20} className={uploadStatus === "success" ? "text-green-400" : "text-slate-500"} />
            }
            {file
              ? <span className="text-xs font-medium text-green-300 text-center break-all">{file.name}</span>
              : <>
                  <span className="text-xs text-slate-400">Glissez votre fichier polaire ici</span>
                  <span className="text-xs text-slate-600">PDF · CSV · XLSX</span>
                </>
            }
          </div>

          <StatusBadge status={uploadStatus} detail={uploadDetail} />

          {/* VMG table */}
          {polarData?.vmg_summary && (
            <div className="overflow-x-auto rounded-xl border border-slate-700/40 bg-slate-800/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-800/80 border-b border-slate-700/60">
                    <th rowSpan={2} className="py-2 px-2 text-center text-blue-300 font-bold align-middle">
                      TWS<br /><span className="text-slate-500 font-normal">kts</span>
                    </th>
                    <th colSpan={3} className="py-1 px-2 text-center text-green-400 font-semibold border-r border-slate-700/40">↑ Près</th>
                    <th colSpan={3} className="py-1 px-2 text-center text-amber-400 font-semibold">↓ Portant</th>
                  </tr>
                  <tr className="bg-slate-800/60 border-b border-slate-700/60">
                    {["TWA", "BS", "VMG", "TWA", "BS", "VMG"].map((h, i) => (
                      <th key={i} className={`py-1 px-1 font-medium text-slate-400 ${i === 2 ? "border-r border-slate-700/40" : ""}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {VMG_TWS_KEYS.map((tws) => (
                    <VmgRow key={tws} tws={tws} entry={polarData.vmg_summary[tws]} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

        </div>
      </div>
    </>
  );
}
