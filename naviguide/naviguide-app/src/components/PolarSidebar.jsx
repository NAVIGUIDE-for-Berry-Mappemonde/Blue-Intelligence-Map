/**
 * NAVIGUIDE — Polar Sidebar (right panel, polar tab)
 * ─────────────────────────────────────────────────────
 * Three sections:
 *   1. UPLOAD   — PDF drag-and-drop / file pick → POST /api/v1/polar/upload
 *   2. VMG TABLE — interactive polar summary (upwind/downwind per TWS) after upload
 *   3. CHAT     — polar agent chat (Anthropic-backed) → POST /api/v1/polar/chat
 *
 * Props:
 *   open        {boolean}  panel visibility
 *   onToggle    {fn}       toggle open/close
 *   exportOpen  {boolean}  whether ExportSidebar is open (affects toggle-btn offset)
 */

import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft, ChevronRight, Upload, Send,
  Compass, TriangleAlert, CheckCircle2, Loader2,
} from "lucide-react";
import { useLang } from "../i18n/LangContext.jsx";

const POLAR_API_URL = import.meta.env.VITE_POLAR_API_URL ?? "http://localhost:8004";

/* ── TWS values shown in the VMG table ─────────────────────────────────────── */
const VMG_TWS_KEYS = ["8", "10", "12", "16", "20", "25"];

/* ── Helpers ─────────────────────────────────────────────────────────────────── */

function kts(v) {
  return v != null ? `${Number(v).toFixed(1)} kt` : "—";
}
function deg(v) {
  return v != null ? `${Math.round(v)}°` : "—";
}

/* ── Sub-components ──────────────────────────────────────────────────────────── */

function SectionTitle({ icon, label }) {
  return (
    <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">
      {icon}
      {label}
    </div>
  );
}

function StatusBadge({ status, detail }) {
  const cfg = {
    uploading: { icon: <Loader2 size={13} className="animate-spin" />, color: "text-blue-400",  bg: "bg-blue-900/30",  text: "Uploading…" },
    success:   { icon: <CheckCircle2 size={13} />,                     color: "text-green-400", bg: "bg-green-900/30", text: "Upload successful" },
    error:     { icon: <TriangleAlert size={13} />,                    color: "text-red-400",   bg: "bg-red-900/30",   text: "Upload failed" },
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

/** Compact VMG row in the table */
function VmgRow({ tws, entry }) {
  const uw = entry?.upwind   ?? {};
  const dw = entry?.downwind ?? {};
  return (
    <tr className="border-b border-slate-700/40 hover:bg-slate-800/40 transition-colors">
      <td className="py-1.5 pl-2 pr-1 text-center font-bold text-blue-300 text-xs w-10">{tws}</td>
      {/* Upwind */}
      <td className="py-1.5 px-1 text-center text-xs text-green-300">{deg(uw.twa)}</td>
      <td className="py-1.5 px-1 text-center text-xs text-slate-200">{kts(uw.speed)}</td>
      <td className="py-1.5 px-1 text-center text-xs font-semibold text-green-400">{kts(uw.vmg)}</td>
      {/* Separator */}
      <td className="py-1.5 px-0.5 text-slate-600 text-center text-xs">│</td>
      {/* Downwind */}
      <td className="py-1.5 px-1 text-center text-xs text-amber-300">{deg(dw.twa)}</td>
      <td className="py-1.5 px-1 text-center text-xs text-slate-200">{kts(dw.speed)}</td>
      <td className="py-1.5 pr-2 pl-1 text-center text-xs font-semibold text-amber-400">{kts(dw.vmg)}</td>
    </tr>
  );
}

function ChatBubble({ role, content }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-2`}>
      <div
        className={`max-w-[85%] px-3 py-2 rounded-xl text-xs leading-relaxed whitespace-pre-wrap
          ${isUser
            ? "bg-blue-600 text-white rounded-br-none"
            : "bg-slate-700/80 text-slate-200 rounded-bl-none border border-slate-600/40"
          }`}
      >
        {content}
      </div>
    </div>
  );
}

/* ── Main component ────────────────────────────────────────────────────────── */

export function PolarSidebar({ open, onToggle, exportOpen }) {
  const { t } = useLang();

  /* Upload state */
  const [file,          setFile]          = useState(null);
  const [expeditionId,  setExpeditionId]  = useState("berry-mappemonde-2026");
  const [boatName,      setBoatName]      = useState("");
  const [uploadStatus,  setUploadStatus]  = useState(null);   // null | "uploading" | "success" | "error"
  const [uploadDetail,  setUploadDetail]  = useState("");
  const [polarData,     setPolarData]     = useState(null);   // vmg_summary etc after upload
  const [isDragging,    setIsDragging]    = useState(false);
  const fileInputRef                      = useRef(null);

  /* Chat state */
  const [messages,   setMessages]   = useState([]);
  const [chatInput,  setChatInput]  = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef                  = useRef(null);

  /* Active section tab */
  const [activeTab, setActiveTab] = useState("upload"); // "upload" | "vmg" | "chat"

  /* Auto-scroll chat */
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /* Switch to VMG tab after successful upload */
  useEffect(() => {
    if (uploadStatus === "success" && polarData) setActiveTab("vmg");
  }, [uploadStatus, polarData]);

  /* ── Drag handlers ──────────────────────────────────────────────────────── */
  const handleDragOver  = (e) => { e.preventDefault(); setIsDragging(true);  };
  const handleDragLeave = ()  => setIsDragging(false);
  const handleDrop      = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f?.name?.endsWith(".pdf")) setFile(f);
  };

  /* ── Upload ─────────────────────────────────────────────────────────────── */
  const handleUpload = async () => {
    if (!file || !expeditionId.trim()) return;
    setUploadStatus("uploading");
    setUploadDetail("");

    const form = new FormData();
    form.append("file",          file);
    form.append("expedition_id", expeditionId.trim());
    if (boatName.trim()) form.append("boat_name", boatName.trim());

    try {
      const res  = await fetch(`${POLAR_API_URL}/api/v1/polar/upload`, { method: "POST", body: form });
      const data = await res.json();

      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);

      setPolarData({
        expedition_id: data.expedition_id,
        boat_name:     data.boat_name,
        grid_shape:    data.grid_shape,
        vmg_summary:   data.vmg_summary,
        created_at:    data.created_at,
      });
      setUploadStatus("success");
      setUploadDetail(`${data.boat_name} — ${data.raw_rows} TWA × ${data.raw_cols} TWS`);

      // Inject welcome chat message
      setMessages([{
        role:    "assistant",
        content: `Polaires chargées pour **${data.boat_name}**.\nGrille ${data.grid_shape[0]}×${data.grid_shape[1]}. Posez-moi vos questions de performance !`,
      }]);
    } catch (err) {
      setUploadStatus("error");
      setUploadDetail(String(err.message ?? err));
    }
  };

  /* ── Chat send ──────────────────────────────────────────────────────────── */
  const handleChatSend = async () => {
    const msg = chatInput.trim();
    if (!msg || chatLoading || !polarData?.expedition_id) return;

    const userMsg    = { role: "user", content: msg };
    const nextHistory = [...messages, userMsg];
    setMessages(nextHistory);
    setChatInput("");
    setChatLoading(true);

    try {
      const res  = await fetch(`${POLAR_API_URL}/api/v1/polar/chat`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({
          expedition_id: polarData.expedition_id,
          message:       msg,
          history:       messages.slice(-6), // last 6 messages as context
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);

      setMessages([...nextHistory, { role: "assistant", content: data.reply }]);
    } catch (err) {
      setMessages([...nextHistory, { role: "assistant", content: `⚠️ ${err.message}` }]);
    } finally {
      setChatLoading(false);
    }
  };

  /* ── Keyboard: Enter to send ─────────────────────────────────────────────── */
  const handleChatKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleChatSend(); }
  };

  /* ── Toggle button right offset ─────────────────────────────────────────── */
  const toggleRight = open
    ? exportOpen ? "right-[648px]" : "right-[326px]"
    : exportOpen ? "right-[326px]" : "right-4";

  /* ── Panel right offset (sits to the left of ExportSidebar if both open) ── */
  const panelRight = exportOpen ? "320px" : "0px";

  /* ── Render ─────────────────────────────────────────────────────────────── */
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

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="px-4 pt-4 pb-3 border-b border-slate-700/60 flex-shrink-0">
          <div className="flex items-center gap-2 mb-3">
            <Compass size={16} className="text-blue-400 flex-shrink-0" />
            <span className="text-sm font-bold text-white">Polaires</span>
            {polarData && (
              <span className="ml-auto text-xs text-green-400 bg-green-900/30 px-2 py-0.5 rounded-full font-medium">
                {polarData.boat_name}
              </span>
            )}
          </div>

          {/* Tab bar */}
          <div className="flex bg-slate-800 rounded-full p-0.5 gap-0.5">
            {[
              { key: "upload", label: "Upload" },
              { key: "vmg",    label: "VMG",    disabled: !polarData },
              { key: "chat",   label: "Chat",   disabled: !polarData },
            ].map(({ key, label, disabled }) => (
              <button
                key={key}
                disabled={disabled}
                onClick={() => setActiveTab(key)}
                className={`flex-1 py-1 rounded-full text-xs font-bold transition-colors
                  ${activeTab === key ? "bg-blue-600 text-white" : "text-slate-400 hover:text-white"}
                  ${disabled ? "opacity-30 cursor-not-allowed" : ""}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* ── UPLOAD TAB ─────────────────────────────────────────────────── */}
        {activeTab === "upload" && (
          <div className="flex-1 overflow-y-auto sidebar-scroll px-4 py-4 space-y-4">
            <SectionTitle icon={<Upload size={11} className="text-blue-400" />} label="Charger les polaires" />

            {/* Expedition ID */}
            <div className="space-y-1">
              <label className="text-xs text-slate-400">ID expédition</label>
              <input
                type="text"
                value={expeditionId}
                onChange={(e) => setExpeditionId(e.target.value)}
                placeholder="berry-mappemonde-2026"
                className="w-full bg-slate-800 border border-slate-600/60 rounded-lg px-3 py-2
                  text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
            </div>

            {/* Boat name (optional) */}
            <div className="space-y-1">
              <label className="text-xs text-slate-400">Nom du bateau <span className="text-slate-600">(optionnel)</span></label>
              <input
                type="text"
                value={boatName}
                onChange={(e) => setBoatName(e.target.value)}
                placeholder="ex. Pen Duick VI"
                className="w-full bg-slate-800 border border-slate-600/60 rounded-lg px-3 py-2
                  text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
              />
            </div>

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
                  : file
                    ? "border-green-500/60 bg-green-900/10"
                    : "border-slate-600 hover:border-slate-500 bg-slate-800/40"}`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <Upload size={20} className={file ? "text-green-400" : "text-slate-500"} />
              {file
                ? <span className="text-xs font-medium text-green-300 text-center break-all">{file.name}</span>
                : <>
                    <span className="text-xs text-slate-400">Glissez votre PDF polaire ici</span>
                    <span className="text-xs text-slate-600">ou cliquez pour choisir</span>
                  </>
              }
            </div>

            {/* Status badge */}
            <StatusBadge status={uploadStatus} detail={uploadDetail} />

            {/* Upload button */}
            <button
              onClick={handleUpload}
              disabled={!file || !expeditionId.trim() || uploadStatus === "uploading"}
              className={`w-full py-2.5 rounded-xl text-xs font-bold transition-all
                ${(!file || !expeditionId.trim() || uploadStatus === "uploading")
                  ? "bg-slate-700 text-slate-500 cursor-not-allowed"
                  : "bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/40 active:scale-[0.98]"}`}
            >
              {uploadStatus === "uploading"
                ? <span className="flex items-center justify-center gap-2"><Loader2 size={12} className="animate-spin" /> Analyse en cours…</span>
                : "Charger et analyser les polaires"
              }
            </button>

            {uploadStatus === "success" && (
              <p className="text-xs text-slate-500 text-center">
                Consultez l'onglet VMG pour le tableau de performance.
              </p>
            )}
          </div>
        )}

        {/* ── VMG TABLE TAB ──────────────────────────────────────────────── */}
        {activeTab === "vmg" && polarData && (
          <div className="flex-1 overflow-y-auto sidebar-scroll px-4 py-4">
            <SectionTitle icon={<Compass size={11} className="text-blue-400" />} label="Tableau VMG" />

            {/* Metadata */}
            <div className="bg-slate-800/60 rounded-xl px-3 py-2 mb-3 border border-slate-700/40 text-xs space-y-1">
              <div className="flex justify-between">
                <span className="text-slate-400">Bateau</span>
                <span className="text-white font-medium">{polarData.boat_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Grille</span>
                <span className="text-white">{polarData.grid_shape?.[0]}×{polarData.grid_shape?.[1]}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-400">Expédition</span>
                <span className="text-blue-300 truncate max-w-[140px]">{polarData.expedition_id}</span>
              </div>
            </div>

            {/* VMG table */}
            <div className="overflow-x-auto rounded-xl border border-slate-700/40 bg-slate-800/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-800/80 border-b border-slate-700/60">
                    <th rowSpan={2} className="py-2 px-2 text-center text-blue-300 font-bold align-middle">TWS<br /><span className="text-slate-500 font-normal">kts</span></th>
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
                    <VmgRow key={tws} tws={tws} entry={polarData.vmg_summary?.[tws]} />
                  ))}
                </tbody>
              </table>
            </div>

            <p className="text-xs text-slate-600 mt-2 text-center">
              BS = vitesse bateau · VMG = vitesse fond cap
            </p>

            {/* CTA to chat */}
            <button
              onClick={() => setActiveTab("chat")}
              className="w-full mt-3 py-2 rounded-xl text-xs font-bold bg-slate-700 hover:bg-slate-600
                text-slate-300 transition-colors"
            >
              Poser une question sur les polaires →
            </button>
          </div>
        )}

        {/* ── CHAT TAB ───────────────────────────────────────────────────── */}
        {activeTab === "chat" && (
          <div className="flex-1 flex flex-col min-h-0">
            {/* Messages area */}
            <div className="flex-1 overflow-y-auto sidebar-scroll px-4 py-3 space-y-1">
              {messages.length === 0 && (
                <div className="text-xs text-slate-500 text-center mt-8">
                  Posez une question sur les performances polaires du bateau.
                </div>
              )}
              {messages.map((m, i) => (
                <ChatBubble key={i} role={m.role} content={m.content} />
              ))}
              {chatLoading && (
                <div className="flex justify-start mb-2">
                  <div className="bg-slate-700/60 border border-slate-600/40 px-3 py-2 rounded-xl rounded-bl-none">
                    <Loader2 size={12} className="animate-spin text-blue-400" />
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Suggested prompts (if no messages yet from user) */}
            {messages.filter(m => m.role === "user").length === 0 && polarData && (
              <div className="px-4 pb-2 flex flex-wrap gap-1">
                {[
                  "VMG optimal au près à 12 nœuds ?",
                  "Angle de gybe recommandé ?",
                  "ETA pour 500 nm à 16 nœuds de vent ?",
                ].map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => { setChatInput(prompt); }}
                    className="text-xs px-2 py-1 bg-slate-700/70 hover:bg-slate-600 text-slate-300
                      rounded-full border border-slate-600/40 transition-colors"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            )}

            {/* Input bar */}
            <div className="flex-shrink-0 px-4 pb-4 pt-2 border-t border-slate-700/60">
              <div className="flex gap-2 items-end">
                <textarea
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={handleChatKeyDown}
                  placeholder="Posez votre question polaire…"
                  rows={2}
                  className="flex-1 bg-slate-800 border border-slate-600/60 rounded-xl px-3 py-2
                    text-xs text-white placeholder-slate-500 resize-none
                    focus:outline-none focus:border-blue-500 leading-relaxed"
                />
                <button
                  onClick={handleChatSend}
                  disabled={!chatInput.trim() || chatLoading}
                  className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0
                    transition-all ${(!chatInput.trim() || chatLoading)
                      ? "bg-slate-700 text-slate-500 cursor-not-allowed"
                      : "bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/40 active:scale-95"}`}
                >
                  <Send size={14} />
                </button>
              </div>
              <p className="text-xs text-slate-600 mt-1 text-center">
                Entrée pour envoyer · Maj+Entrée pour nouvelle ligne
              </p>
            </div>
          </div>
        )}

      </div>
    </>
  );
}
