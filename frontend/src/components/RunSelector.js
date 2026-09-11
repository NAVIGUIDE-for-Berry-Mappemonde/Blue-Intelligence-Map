import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight } from "lucide-react";
import api from "../api";
import { fetchRunsOnce } from "../lib/runCache";

// Endpoint « liste des runs » par mode. PoE = poe_runs, les autres = runs isolés.
const RUNS_ENDPOINT = {
  projects: "/projects/runs",
  marinas: "/marinas/runs",
  capitaineries: "/capitaineries/runs",
  formalities: "/poe/runs",
  amp: "/amp/runs",
};

const fmtDate = (iso) => {
  if (!iso) return "";
  return String(iso).slice(0, 16).replace("T", " ");
};

/**
 * RunSelector — petit bouton " > " accolé à l'onglet Map.
 *
 * Ouvre la liste des runs disponibles pour le mode courant ; sélectionner un
 * run l'affiche sur la carte à la place des données live. « Carte live »
 * revient à l'affichage par défaut.
 */
export default function RunSelector({ mode, mapRun, onSelect, t }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [runs, setRuns] = useState([]);
  // Position fixe calculée depuis le bouton : le groupe d'onglets du Header
  // est en overflow-hidden, un menu absolu y serait rogné.
  const [pos, setPos] = useState({ top: 0, right: 0 });
  const boxRef = useRef(null);
  const btnRef = useRef(null);

  useEffect(() => { setOpen(false); }, [mode]);

  const toggle = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) });
    }
    setOpen((o) => !o);
  };

  useEffect(() => {
    if (!open) return undefined;
    let alive = true;
    setLoading(true);
    fetchRunsOnce(mode, () => api.get(RUNS_ENDPOINT[mode] || RUNS_ENDPOINT.projects).then(({ data }) => data?.items || []))
      .then((items) => { if (alive) setRuns(items || []); })
      .catch(() => { if (alive) setRuns([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [open, mode]);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const pick = (run) => {
    onSelect(run);
    setOpen(false);
  };

  return (
    <div ref={boxRef} className="relative flex">
      <button
        ref={btnRef}
        data-testid="run-selector-btn"
        onClick={toggle}
        title={t("runSelectorTitle")}
        className={`flex items-center gap-1 px-2.5 py-1.5 text-xs font-semibold border-l border-line transition-colors ${
          mapRun || open
            ? "bg-accent/15 text-accent"
            : "text-slate-400 hover:text-slate-200 hover:bg-raised"
        }`}
      >
        {/* Libellé visible (le chevron seul passait inaperçu) */}
        {!mapRun && <span>{t("runSelectorLabel")}</span>}
        <ChevronRight
          size={13}
          className={`transition-transform ${open ? "rotate-90" : ""}`}
        />
        {mapRun && (
          <span
            data-testid="run-selector-current"
            className="font-mono text-[10px] max-w-[110px] truncate"
          >
            {mapRun.label || mapRun.id}
          </span>
        )}
      </button>
      {open && (
        <div
          data-testid="run-selector-list"
          style={{ position: "fixed", top: pos.top, right: pos.right }}
          className="w-80 max-h-96 overflow-y-auto border border-line bg-surface rounded-sm shadow-2xl z-[1400]"
        >
          <div className="px-3 py-2 border-b border-line font-mono text-[10px] uppercase tracking-[0.15em] text-slate-500">
            {t("runSelectorTitle")} — {mode}
          </div>
          <button
            data-testid="run-option-live"
            onClick={() => pick(null)}
            className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-left text-xs border-b border-line/60 ${
              !mapRun ? "bg-accent/10 text-accent" : "text-slate-300 hover:bg-raised"
            }`}
          >
            <span className="font-semibold">{t("runSelectorLive")}</span>
            {!mapRun && <Check size={13} />}
          </button>
          {loading ? (
            <div className="px-3 py-3 text-xs text-slate-500">{t("runSelectorLoading")}</div>
          ) : runs.length === 0 ? (
            <div data-testid="run-selector-empty" className="px-3 py-3 text-xs text-slate-500">
              {t("runSelectorEmpty")}
            </div>
          ) : (
            runs.map((r) => {
              const selected = mapRun?.id === r.id;
              const count = r.count ?? r.counters?.sites;
              return (
                <button
                  key={r.id}
                  data-testid={`run-option-${r.id}`}
                  onClick={() => pick({ id: r.id, label: r.label || r.id })}
                  className={`w-full px-3 py-2 text-left border-b border-line/40 last:border-b-0 ${
                    selected ? "bg-accent/10" : "hover:bg-raised"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`text-xs font-semibold truncate ${selected ? "text-accent" : "text-slate-200"}`}>
                      {r.label || r.id}
                    </span>
                    {selected && <Check size={13} className="text-accent shrink-0" />}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 font-mono text-[10px] text-slate-500">
                    <span className="truncate">{r.id}</span>
                    {r.state && <span className={r.state === "done" ? "text-bio" : ""}>{r.state}</span>}
                    {count != null && <span>{count} pts</span>}
                    <span>{fmtDate(r.created_at)}</span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
