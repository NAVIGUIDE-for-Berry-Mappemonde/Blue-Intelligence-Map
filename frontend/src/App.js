import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "./api";
import { makeT } from "./i18n";
import Header from "./components/Header";
import SwarmPanel from "./components/SwarmPanel";
import MarinasPanel from "./components/MarinasPanel";
import FormalitiesPanel from "./components/FormalitiesPanel";
import MapView from "./components/MapView";
import AuditView from "./components/AuditView";
import ReviewView from "./components/ReviewView";
import SettingsPanel from "./components/SettingsPanel";
import ReportModal from "./components/ReportModal";

// Read the persisted mode on boot. Default = "projects". (Phase 4A — 3 modes)
const readInitialMode = () => {
  try {
    const v = localStorage.getItem("bi.mode");
    if (v === "marinas" || v === "projects" || v === "formalities") return v;
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
  const [showReport, setShowReport] = useState(false);
  const [categories, setCategories] = useState([]);
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [marinas, setMarinas] = useState({ type: "FeatureCollection", features: [] });
  const [flyToMarina, setFlyToMarina] = useState(null); // {id, lat, lon} used as a one-shot signal
  // Phase 8 — Anchorages (mouillages) layer
  const [anchorages, setAnchorages] = useState({ type: "FeatureCollection", features: [] });
  const [showAnchorages, setShowAnchoragesRaw] = useState(() => {
    try { return localStorage.getItem("bi.showAnchorages") !== "0"; } catch (_) { return true; }
  });
  const setShowAnchorages = useCallback((v) => {
    setShowAnchoragesRaw(v);
    try { localStorage.setItem("bi.showAnchorages", v ? "1" : "0"); } catch (_) { /* ignore */ }
  }, []);
  // Refactor 2026-06 — Formalities mode = world [EEZ -> Ports of Entry]
  const [poeZones, setPoeZones] = useState({ count: 0, summary: null, items: [] });
  const [poePorts, setPoePorts] = useState({ type: "FeatureCollection", features: [] });
  const [selectedZone, setSelectedZone] = useState(null);   // mrgid
  const [flyToZone, setFlyToZone] = useState(null);         // {mrgid, bbox, ts}
  const [zoneFiche, setZoneFiche] = useState(null);
  const [ficheLoading, setFicheLoading] = useState(false);
  const [flyToPoe, setFlyToPoe] = useState(null);
  // Phase 7bis stabilisation — memoise `t` so its reference stays stable
  // across selection setStates. Otherwise every `handleSelectEscale` call
  // creates a fresh `t` → MapView props change → the formalities marker
  // rebuild useEffect re-fires and the DOM briefly drops to 0 markers.
  const t = useMemo(() => makeT(lang), [lang]);
  const lastTotalRef = useRef(-1);
  const viewRef = useRef(view);
  viewRef.current = view;

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
        const p = await api.get("/projects");
        setProjects(p.data);
        lastTotalRef.current = f.data.total;
      }
    } catch (e) { /* transient */ }
  }, []);

  const fetchSettings = useCallback(async () => {
    try {
      const { data } = await api.get("/settings");
      setSettings(data);
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

  // Phase 8 — anchorages fetcher
  const fetchAnchorages = useCallback(async () => {
    try {
      const { data } = await api.get("/anchorages");
      setAnchorages(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchPoeZones = useCallback(async () => {
    try {
      const { data } = await api.get("/poe/zones");
      setPoeZones(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchPoePorts = useCallback(async () => {
    try {
      const { data } = await api.get("/poe/ports");
      setPoePorts(data);
    } catch (e) { /* transient */ }
  }, []);

  useEffect(() => {
    // Phase 3.1 — async enrichment via 202 + poll status.
    // Polls every 2.5s until state != "running" (max ~180s).
    const pollUntilDone = async (endpoint, onDone, onErr, maxAttempts = 72) => {
      for (let i = 0; i < maxAttempts; i++) {
        // 2.5s between polls
        await new Promise((res) => setTimeout(res, 2500));
        try {
          const st = await api.get(endpoint);
          const s = st.data?.state;
          if (s === "done") { onDone(st.data); return; }
          if (s === "error") { onErr(st.data?.error || "enrichment failed"); return; }
        } catch (e) { /* transient */ }
      }
      onErr("timeout after ~3min");
    };

    window.__biEnrichMarina = async (marinaId) => {
      const btn = document.querySelector(`[data-testid="popup-enrich-btn"]`);
      const setBtn = (label, color) => {
        if (!btn) return;
        btn.textContent = label;
        if (color) btn.style.color = color;
      };
      try {
        if (btn) btn.disabled = true;
        setBtn("◆ " + (lang === "fr" ? "Enrichissement…" : "Enriching…"));
        // 202 kick-off (<5s)
        const kick = await api.post(`/marinas/${marinaId}/enrich`);
        if (kick.status !== 202 && kick.status !== 200) {
          setBtn("◆ " + (lang === "fr" ? "Échec" : "Failed"), "#fbbf24");
          return;
        }
        // Poll
        await pollUntilDone(
          `/marinas/${marinaId}/enrich/status`,
          async (data) => {
            await fetchMarinas();
            const m = data.result || {};
            setFlyToMarina({ id: marinaId, lat: m.lat, lon: m.lon, ts: Date.now() });
          },
          (err) => {
            setBtn("◆ " + (lang === "fr" ? "Échec" : "Failed"), "#fbbf24");
            if (btn) btn.title = String(err).slice(0, 200);
          },
        );
      } catch (e) {
        // 409 = already running — attach the poller anyway
        if (e?.response?.status === 409) {
          await pollUntilDone(
            `/marinas/${marinaId}/enrich/status`,
            async (data) => {
              await fetchMarinas();
              const m = data.result || {};
              setFlyToMarina({ id: marinaId, lat: m.lat, lon: m.lon, ts: Date.now() });
            },
            (err) => setBtn("◆ " + (lang === "fr" ? "Échec" : "Failed"), "#fbbf24"),
          );
        } else {
          setBtn("◆ " + (lang === "fr" ? "Échec" : "Failed"), "#fbbf24");
          console.warn("marina enrich failed", e);
        }
      }
    };

    window.__biEnrichProject = async (projectId) => {
      const btn = document.querySelector(`[data-testid="popup-project-enrich-btn"]`);
      const setBtn = (label, color) => {
        if (!btn) return;
        btn.textContent = label;
        if (color) btn.style.color = color;
      };
      try {
        if (btn) btn.disabled = true;
        setBtn("↻ " + (lang === "fr" ? "Rafraîchissement…" : "Refreshing…"));
        const kick = await api.post(`/projects/${projectId}/enrich`);
        if (kick.status !== 202 && kick.status !== 200) {
          setBtn("↻ " + (lang === "fr" ? "Échec" : "Failed"), "#fbbf24");
          return;
        }
        await pollUntilDone(
          `/projects/${projectId}/enrich/status`,
          async () => {
            await fetchProjects(true);
            setBtn("✓ " + (lang === "fr" ? "Rafraîchi" : "Refreshed"), "#39ff14");
          },
          (err) => {
            setBtn("↻ " + (lang === "fr" ? "Échec" : "Failed"), "#fbbf24");
            if (btn) btn.title = String(err).slice(0, 200);
          },
        );
      } catch (e) {
        if (e?.response?.status === 409) {
          await pollUntilDone(
            `/projects/${projectId}/enrich/status`,
            async () => {
              await fetchProjects(true);
              setBtn("✓ " + (lang === "fr" ? "Rafraîchi" : "Refreshed"), "#39ff14");
            },
            (err) => setBtn("↻ " + (lang === "fr" ? "Échec" : "Failed"), "#fbbf24"),
          );
        } else {
          setBtn("↻ " + (lang === "fr" ? "Échec" : "Failed"), "#fbbf24");
          console.warn("project enrich failed", e);
        }
      }
    };

    return () => {
      delete window.__biEnrichMarina;
      delete window.__biEnrichProject;
    };
  }, [fetchMarinas, fetchProjects, lang]);

  useEffect(() => {
    fetchStatus();
    fetchProjects();
    fetchSettings();
    fetchCategories();
    fetchMarinas();
    fetchAnchorages();
    fetchPoeZones();
    fetchPoePorts();
    const unlessReview = (fn) => () => {
      if (viewRef.current === "review") return;
      fn();
    };
    const s = setInterval(fetchStatus, 2000);
    const p = setInterval(unlessReview(() => fetchProjects()), 5000);
    const c = setInterval(fetchCategories, 15000);
    // Marinas refresh only when a build might be running — a light 8s poll.
    const m = setInterval(unlessReview(fetchMarinas), 8000);
    const a = setInterval(unlessReview(fetchAnchorages), 10000);
    const z = setInterval(unlessReview(fetchPoeZones), 12000);
    const pp = setInterval(unlessReview(fetchPoePorts), 12000);
    return () => { clearInterval(s); clearInterval(p); clearInterval(c); clearInterval(m); clearInterval(a); clearInterval(z); clearInterval(pp); };
  }, [fetchStatus, fetchProjects, fetchSettings, fetchCategories, fetchMarinas, fetchAnchorages, fetchPoeZones, fetchPoePorts]);

  // Handler passed to MarinasPanel — sets a one-shot fly target consumed by MapView
  const handleFlyToMarina = useCallback((id, lat, lon) => {
    setFlyToMarina({ id, lat, lon, ts: Date.now() });
  }, []);

  // Refactor 2026-06 — Handler wired to the sidebar rows and the EEZ polygons:
  // selects the zone; when a bbox is supplied (sidebar click), also flies to it.
  const handleSelectZone = useCallback((mrgid, bbox, anchor) => {
    setSelectedZone(mrgid);
    if (bbox && Array.isArray(bbox) && bbox.length === 4) {
      setFlyToZone({ mrgid, bbox, anchor: anchor || null, ts: Date.now() });
    }
  }, []);

  const handleFlyToPoe = useCallback((port) => {
    if (!port || port.lat == null || port.lon == null) return;
    setFlyToPoe({ ...port, ts: Date.now() });
  }, []);

  useEffect(() => {
    if (!selectedZone) {
      setZoneFiche(null);
      setFicheLoading(false);
      return;
    }
    let alive = true;
    setFicheLoading(true);
    api.get(`/poe/zones/${selectedZone}`)
      .then(({ data }) => { if (alive) setZoneFiche(data); })
      .catch(() => { if (alive) setZoneFiche(null); })
      .finally(() => { if (alive) setFicheLoading(false); });
    return () => { alive = false; };
  }, [selectedZone]);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-abyss" data-mode={mode}>
      <Header
        lang={lang} setLang={setLang} view={view} setView={setView}
        showSettings={showSettings} setShowSettings={setShowSettings}
        status={status} t={t} basemap={basemap} setBasemap={setBasemap}
        mode={mode} setMode={setMode}
      />
      <div className="flex flex-1 min-h-0">
        {view !== "review" && mode === "projects" && (
          <SwarmPanel
            t={t} projects={projects} funders={funders}
            funderFilter={funderFilter} setFunderFilter={setFunderFilter}
            searchQuery={searchQuery} setSearchQuery={setSearchQuery}
            categories={categories} categoryFilter={categoryFilter} setCategoryFilter={setCategoryFilter}
            onReport={() => setShowReport(true)}
          />
        )}
        {view !== "review" && mode === "marinas" && (
          <MarinasPanel
            t={t}
            marinas={marinas}
            onFlyTo={handleFlyToMarina}
            onRefresh={fetchMarinas}
            onRefreshAnchorages={fetchAnchorages}
          />
        )}
        {view !== "review" && mode === "formalities" && (
          <FormalitiesPanel
            t={t}
            zones={poeZones}
            selectedZone={selectedZone}
            onSelectZone={handleSelectZone}
            fiche={zoneFiche}
            ficheLoading={ficheLoading}
            onFlyToPort={handleFlyToPoe}
          />
        )}
        <main className="flex-1 relative min-w-0">
          {view === "map" ? (
            <MapView
              mode={mode}
              projects={projects}
              marinas={marinas}
              anchorages={anchorages}
              showAnchorages={showAnchorages}
              poeZones={poeZones.items}
              poePorts={poePorts}
              onSelectZone={handleSelectZone}
              flyToMarina={flyToMarina}
              flyToZone={flyToZone}
              flyToPoe={flyToPoe}
              zoneFiche={zoneFiche}
              funderFilter={funderFilter} searchQuery={searchQuery} t={t}
              basemap={basemap} categories={categories} categoryFilter={categoryFilter}
              maxMarkers={settings?.max_markers || 1000} minZoom={settings?.min_zoom || 2} />
          ) : view === "audit" ? (
            <AuditView t={t} mode={mode} status={status} refresh={() => { fetchStatus(); fetchProjects(); }}
              onPoeRefresh={() => { fetchPoeZones(); fetchPoePorts(); }}
              showAnchorages={showAnchorages} setShowAnchorages={setShowAnchorages}
              anchoragesCount={anchorages?.features?.length || 0} />
          ) : (
            <ReviewView t={t} mode={mode} />
          )}
        </main>
          {showSettings && (
          <SettingsPanel t={t} lang={lang} mode={mode} settings={settings}
            onSaved={fetchSettings}
            // 2026-08-24 bug-fix — import router-callback receives the mode
            // that was actually imported so we only refresh the affected
            // dataset (never both, to avoid unnecessary re-fetches).
            onImported={(importedMode) => {
              if (importedMode === "marinas") fetchMarinas();
              else fetchProjects(true);
            }}
            onProjectsCleared={() => fetchProjects(true)} onClose={() => setShowSettings(false)} />
        )}
      </div>
      {showReport && (
        <ReportModal t={t} onClose={() => setShowReport(false)} onSubmitted={() => { setShowReport(false); }} />
      )}
    </div>
  );
}
