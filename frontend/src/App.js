import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "./api";
import { makeT } from "./i18n";
import Header from "./components/Header";
import SwarmPanel from "./components/SwarmPanel";
import MarinasPanel from "./components/MarinasPanel";
import FormalitiesPanel from "./components/FormalitiesPanel";
import MapView from "./components/MapView";
import AuditView from "./components/AuditView";
import SettingsPanel from "./components/SettingsPanel";
import { DonateModal, PaymentReturn } from "./components/Donations";
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
  const [donations, setDonations] = useState({ total_eur: 0, count: 0 });
  const [donateTarget, setDonateTarget] = useState(null);
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
  const [route, setRoute] = useState({ type: "FeatureCollection", features: [] });
  const [poeZones, setPoeZones] = useState({ count: 0, summary: null, items: [] });
  const [poePorts, setPoePorts] = useState({ type: "FeatureCollection", features: [] });
  const [selectedZone, setSelectedZone] = useState(null);   // mrgid
  const [flyToZone, setFlyToZone] = useState(null);         // {mrgid, bbox, ts}
  const [paymentReturn, setPaymentReturn] = useState(window.location.pathname.startsWith("/payment/"));
  // Phase 7bis stabilisation — memoise `t` so its reference stays stable
  // across selection setStates. Otherwise every `handleSelectEscale` call
  // creates a fresh `t` → MapView props change → the formalities marker
  // rebuild useEffect re-fires and the DOM briefly drops to 0 markers.
  const t = useMemo(() => makeT(lang), [lang]);
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

  // Phase 8 — anchorages fetcher
  const fetchAnchorages = useCallback(async () => {
    try {
      const { data } = await api.get("/anchorages");
      setAnchorages(data);
    } catch (e) { /* transient */ }
  }, []);

  // ---- Refactor 2026-06: route + EEZ zones + PoE ports ----
  const fetchRoute = useCallback(async () => {
    try {
      const { data } = await api.get("/route");
      setRoute(data);
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
    window.__biDonate = (id) => {
      setDonateTarget({ id, title: null });
    };
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

    // ---- Refactor 2026-06: PoE generation handler (wired to the EEZ map popup) ----
    // Kicks the async pipeline (202) then polls the status until done (~1-6 min)
    // and refreshes zones + ports so the map recolours live.
    window.__biPoeGenState = window.__biPoeGenState || {};
    window.__biGeneratePoeZone = async (mrgid) => {
      // The popup HTML is rebuilt on every zones/ports refetch — re-resolve the
      // button on EVERY update and keep a global gen-state that the popup
      // builder reads so a rebuilt popup renders the "Generating…" state too.
      const setBtn = (label, disabled = true) => {
        const btn = document.querySelector('[data-testid="poe-generate-btn"]');
        if (!btn) return;
        btn.disabled = disabled;
        btn.textContent = label;
      };
      const finish = (label) => {
        delete window.__biPoeGenState[mrgid];
        setBtn(label, false);
      };
      window.__biPoeGenState[mrgid] = "running";
      try {
        const r = await api.post(`/poe/zones/${mrgid}/generate`);
        if (r.status !== 202 && r.status !== 200) {
          finish("↻ " + (lang === "fr" ? "Échec" : "Failed"));
          return;
        }
      } catch (e) {
        if (e?.response?.status !== 409) {
          finish("↻ " + (lang === "fr" ? "Échec" : "Failed"));
          return;
        }
      }
      setBtn("↻ " + (lang === "fr" ? "Génération…" : "Generating…"));
      for (let i = 0; i < 150; i++) {
        await new Promise((res) => setTimeout(res, 3000));
        setBtn("↻ " + (lang === "fr" ? "Génération…" : "Generating…"));
        try {
          const st = await api.get(`/poe/zones/${mrgid}/generate/status`);
          if (st.data?.state === "done") {
            await fetchPoeZones();
            await fetchPoePorts();
            finish("✓ " + (lang === "fr" ? "Générée" : "Generated"));
            return;
          }
          if (st.data?.state === "error") {
            finish("↻ " + (lang === "fr" ? "Échec" : "Failed"));
            return;
          }
        } catch (_) { /* transient */ }
      }
      finish("↻ Timeout");
    };

    return () => {
      delete window.__biDonate;
      delete window.__biEnrichMarina;
      delete window.__biEnrichProject;
      delete window.__biGeneratePoeZone;
    };
  }, [fetchMarinas, fetchProjects, fetchPoeZones, fetchPoePorts, lang]);

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
    fetchAnchorages();
    fetchRoute();
    fetchPoeZones();
    fetchPoePorts();
    const s = setInterval(fetchStatus, 2000);
    const p = setInterval(fetchProjects, 5000);
    const d = setInterval(fetchDonations, 10000);
    const c = setInterval(fetchCategories, 15000);
    // Marinas refresh only when a build might be running — a light 8s poll.
    const m = setInterval(fetchMarinas, 8000);
    const a = setInterval(fetchAnchorages, 10000);
    const z = setInterval(fetchPoeZones, 12000);
    const pp = setInterval(fetchPoePorts, 12000);
    return () => { clearInterval(s); clearInterval(p); clearInterval(d); clearInterval(c); clearInterval(m); clearInterval(a); clearInterval(z); clearInterval(pp); };
  }, [fetchStatus, fetchProjects, fetchSettings, fetchDonations, fetchCategories, fetchMarinas, fetchAnchorages, fetchRoute, fetchPoeZones, fetchPoePorts]);

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

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-abyss" data-mode={mode}>
      <Header
        lang={lang} setLang={setLang} view={view} setView={setView}
        showSettings={showSettings} setShowSettings={setShowSettings}
        status={status} t={t} basemap={basemap} setBasemap={setBasemap}
        donations={donations}
        mode={mode} setMode={setMode}
        onOpenDonate={() => setDonateTarget({ id: null, title: null, global: true })}
      />
      <div className="flex flex-1 min-h-0">
        {mode === "projects" && (
          <SwarmPanel
            t={t} projects={projects} funders={funders}
            funderFilter={funderFilter} setFunderFilter={setFunderFilter}
            searchQuery={searchQuery} setSearchQuery={setSearchQuery}
            categories={categories} categoryFilter={categoryFilter} setCategoryFilter={setCategoryFilter}
            onReport={() => setShowReport(true)}
          />
        )}
        {mode === "marinas" && (
          <MarinasPanel
            t={t}
            marinas={marinas}
            onFlyTo={handleFlyToMarina}
            onRefresh={fetchMarinas}
            onRefreshAnchorages={fetchAnchorages}
          />
        )}
        {mode === "formalities" && (
          <FormalitiesPanel
            t={t}
            zones={poeZones}
            selectedZone={selectedZone}
            onSelectZone={handleSelectZone}
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
              route={route}
              onSelectZone={handleSelectZone}
              flyToMarina={flyToMarina}
              flyToZone={flyToZone}
              funderFilter={funderFilter} searchQuery={searchQuery} t={t}
              basemap={basemap} categories={categories} categoryFilter={categoryFilter}
              maxMarkers={settings?.max_markers || 1000} minZoom={settings?.min_zoom || 2} />
          ) : (
            <AuditView t={t} mode={mode} status={status} refresh={() => { fetchStatus(); fetchProjects(); }}
              onPoeRefresh={() => { fetchPoeZones(); fetchPoePorts(); }}
              showAnchorages={showAnchorages} setShowAnchorages={setShowAnchorages}
              anchoragesCount={anchorages?.features?.length || 0} />
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
