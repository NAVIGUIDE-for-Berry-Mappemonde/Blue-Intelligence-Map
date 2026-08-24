import { useCallback, useEffect, useRef, useState } from "react";
import api from "./api";
import { makeT } from "./i18n";
import Header from "./components/Header";
import SwarmPanel from "./components/SwarmPanel";
import MarinasPanel from "./components/MarinasPanel";
import MapView from "./components/MapView";
import AuditView from "./components/AuditView";
import SettingsPanel from "./components/SettingsPanel";
import { DonateModal, PaymentReturn } from "./components/Donations";
import ReportModal from "./components/ReportModal";

// Read the persisted mode on boot. Default = "projects".
const readInitialMode = () => {
  try {
    const v = localStorage.getItem("bi.mode");
    if (v === "marinas" || v === "projects") return v;
  } catch (_) {
    /* localStorage disabled */
  }
  return "projects";
};

export default function App() {
  const [lang, setLang] = useState("en");
  const [view, setView] = useState("map");
  const [mode, setModeRaw] = useState(readInitialMode());   // 'projects' | 'marinas'
  const [showSettings, setShowSettings] = useState(false);
  const [status, setStatus] = useState(null);
  const [projects, setProjects] = useState({ type: "FeatureCollection", features: [] });
  const [funders, setFunders] = useState({ total: 0, funders: [] });
  const [funderFilter, setFunderFilter] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");
  const [basemap, setBasemap] = useState("dark");
  const [settings, setSettings] = useState(null);
  const [donations, setDonations] = useState({ total_eur: 0, count: 0 });
  const [donateTarget, setDonateTarget] = useState(null);
  const [showReport, setShowReport] = useState(false);
  const [categories, setCategories] = useState([]);
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [marinas, setMarinas] = useState({ type: "FeatureCollection", features: [] });
  const [flyToMarina, setFlyToMarina] = useState(null); // {id, lat, lon} used as a one-shot signal
  const [paymentReturn, setPaymentReturn] = useState(window.location.pathname.startsWith("/payment/"));
  const t = makeT(lang);
  const lastTotalRef = useRef(-1);

  // Persist mode + reflect on <html> for CSS var switching
  const setMode = useCallback((m) => {
    setModeRaw(m);
    try { localStorage.setItem("bi.mode", m); } catch (_) { /* ignore */ }
  }, []);

  useEffect(() => {
    // Set data-mode on <html> so [data-mode="..."] CSS vars kick in globally
    document.documentElement.setAttribute("data-mode", mode);
  }, [mode]);

  const fetchStatus = useCallback(async () => {
    try {
      const { data } = await api.get("/swarm/status");
      setStatus(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchProjects = useCallback(async (force = false) => {
    try {
      const f = await api.get("/funders");
      setFunders(f.data);
      if (force || f.data.total !== lastTotalRef.current) {
        lastTotalRef.current = f.data.total;
        const p = await api.get("/projects");
        setProjects(p.data);
      }
    } catch (e) { /* transient */ }
  }, []);

  const fetchSettings = useCallback(async () => {
    try {
      const { data } = await api.get("/settings");
      setSettings(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchDonations = useCallback(async () => {
    try {
      const { data } = await api.get("/donations/total");
      setDonations(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchCategories = useCallback(async () => {
    try {
      const { data } = await api.get("/categories");
      setCategories(data.groups);
    } catch (e) { /* transient */ }
  }, []);

  const fetchMarinas = useCallback(async () => {
    try {
      const { data } = await api.get("/marinas");
      setMarinas(data);
    } catch (e) { /* transient */ }
  }, []);

  useEffect(() => {
    window.__biDonate = (id) => {
      setDonateTarget({ id, title: null });
    };
    // Phase 3 — global enrichment hooks used from inside Leaflet popup HTML
    window.__biEnrichMarina = async (marinaId) => {
      // Optimistic UI: mark the marina as enriching in state
      try {
        const btn = document.querySelector(`[data-testid="popup-enrich-btn"]`);
        if (btn) { btn.disabled = true; btn.textContent = "◆ " + (lang === "fr" ? "Enrichissement…" : "Enriching…"); }
        const res = await api.post(`/marinas/${marinaId}/enrich`);
        if (res.data?.ok) {
          // Refetch marinas — new data will re-render the popup on next open
          await fetchMarinas();
          // Re-open the popup with fresh data
          setFlyToMarina({ id: marinaId, lat: res.data.marina.lat, lon: res.data.marina.lon, ts: Date.now() });
        } else if (btn) {
          btn.textContent = "◆ " + (lang === "fr" ? "Échec" : "Failed");
          btn.style.color = "#fbbf24";
        }
      } catch (e) {
        console.warn("marina enrich failed", e);
      }
    };
    window.__biEnrichProject = async (projectId) => {
      try {
        const btn = document.querySelector(`[data-testid="popup-project-enrich-btn"]`);
        if (btn) { btn.disabled = true; btn.textContent = "↻ " + (lang === "fr" ? "Rafraîchissement…" : "Refreshing…"); }
        const res = await api.post(`/projects/${projectId}/enrich`);
        if (res.data?.ok) {
          await fetchProjects(true);
          if (btn) {
            btn.textContent = "✓ " + (lang === "fr" ? "Rafraîchi" : "Refreshed");
            btn.style.color = "#39ff14";
          }
        } else if (btn) {
          btn.textContent = "↻ " + (lang === "fr" ? "Échec" : "Failed");
          btn.style.color = "#fbbf24";
          btn.title = res.data?.error || "";
        }
      } catch (e) {
        console.warn("project enrich failed", e);
      }
    };
    return () => {
      delete window.__biDonate;
      delete window.__biEnrichMarina;
      delete window.__biEnrichProject;
    };
  }, [fetchMarinas, fetchProjects, lang]);

  useEffect(() => {
    if (donateTarget && !donateTarget.title) {
      const f = (projects.features || []).find((x) => x.properties.id === donateTarget.id);
      if (f) setDonateTarget({ id: donateTarget.id, title: f.properties.title });
    }
  }, [donateTarget, projects]);

  useEffect(() => {
    fetchStatus();
    fetchProjects();
    fetchSettings();
    fetchDonations();
    fetchCategories();
    fetchMarinas();
    const s = setInterval(fetchStatus, 2000);
    const p = setInterval(fetchProjects, 5000);
    const d = setInterval(fetchDonations, 10000);
    const c = setInterval(fetchCategories, 15000);
    // Marinas refresh only when a build might be running — a light 8s poll.
    const m = setInterval(fetchMarinas, 8000);
    return () => { clearInterval(s); clearInterval(p); clearInterval(d); clearInterval(c); clearInterval(m); };
  }, [fetchStatus, fetchProjects, fetchSettings, fetchDonations, fetchCategories, fetchMarinas]);

  // Handler passed to MarinasPanel — sets a one-shot fly target consumed by MapView
  const handleFlyToMarina = useCallback((id, lat, lon) => {
    setFlyToMarina({ id, lat, lon, ts: Date.now() });
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-abyss" data-mode={mode}>
      <Header
        lang={lang} setLang={setLang} view={view} setView={setView}
        showSettings={showSettings} setShowSettings={setShowSettings}
        status={status} t={t} basemap={basemap} setBasemap={setBasemap}
        donations={donations}
        mode={mode} setMode={setMode}
      />
      <div className="flex flex-1 min-h-0">
        {mode === "projects" ? (
          <SwarmPanel
            t={t} projects={projects} funders={funders}
            funderFilter={funderFilter} setFunderFilter={setFunderFilter}
            searchQuery={searchQuery} setSearchQuery={setSearchQuery}
            categories={categories} categoryFilter={categoryFilter} setCategoryFilter={setCategoryFilter}
            onDonate={(id, title) => setDonateTarget({ id, title })}
            onReport={() => setShowReport(true)}
          />
        ) : (
          <MarinasPanel
            t={t}
            marinas={marinas}
            onFlyTo={handleFlyToMarina}
            onRefresh={fetchMarinas}
          />
        )}
        <main className="flex-1 relative min-w-0">
          {view === "map" ? (
            <MapView
              mode={mode}
              projects={projects}
              marinas={marinas}
              flyToMarina={flyToMarina}
              funderFilter={funderFilter} searchQuery={searchQuery} t={t}
              basemap={basemap} categories={categories} categoryFilter={categoryFilter}
              maxMarkers={settings?.max_markers || 1000} minZoom={settings?.min_zoom || 2} />
          ) : (
            <AuditView t={t} status={status} refresh={() => { fetchStatus(); fetchProjects(); }} />
          )}
        </main>
          {showSettings && (
          <SettingsPanel t={t} lang={lang} settings={settings}
            onSaved={fetchSettings} onImported={() => fetchProjects(true)}
            onProjectsCleared={() => fetchProjects(true)} onClose={() => setShowSettings(false)} />
        )}
      </div>
      {donateTarget && (
        <DonateModal t={t} target={donateTarget} onClose={() => setDonateTarget(null)} />
      )}
      {showReport && (
        <ReportModal t={t} onClose={() => setShowReport(false)} onSubmitted={() => { setShowReport(false); }} />
      )}
      {paymentReturn && (
        <PaymentReturn t={t} onDone={() => { setPaymentReturn(false); fetchDonations(); }} />
      )}
    </div>
  );
}
