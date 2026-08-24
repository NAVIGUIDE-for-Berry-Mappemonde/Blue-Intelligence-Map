import { useCallback, useEffect, useRef, useState } from "react";
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
  // Phase 4A — Formalities mode data
  const [route, setRoute] = useState({ type: "FeatureCollection", features: [] });
  const [territories, setTerritories] = useState(null);
  const [formalities, setFormalities] = useState([]);
  const [selectedTerritory, setSelectedTerritory] = useState(null);
  const [selectedEscale, setSelectedEscale] = useState(null);
  const [flyToEscale, setFlyToEscale] = useState(null); // {name, lat, lon, ts}
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

  // ---- Phase 4A: route + territories + formalities ----
  const fetchRoute = useCallback(async () => {
    try {
      const { data } = await api.get("/route");
      setRoute(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchTerritories = useCallback(async () => {
    try {
      const { data } = await api.get("/territories");
      setTerritories(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchFormalities = useCallback(async () => {
    try {
      const { data } = await api.get("/formalities");
      setFormalities(data?.items || []);
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

    // ---- Phase 4B: formalities generation / verify / immigration handlers ----
    // These do NOT block the UI — they kick off the async task and let
    // FormalitiesPanel poll the status. App.js just refreshes the collection
    // on completion so map + list + card update live.
    window.__biGenerateFormality = async (code) => {
      try {
        const r = await api.post(`/formalities/${code}/generate`);
        if (r.status === 202 || r.status === 200) return { ok: true };
        return { ok: false, code: r.status };
      } catch (e) {
        return { ok: false, code: e?.response?.status || 0, msg: e?.message };
      }
    };
    window.__biVerifyFormality = async (code) => {
      try {
        await api.put(`/formalities/${code}/verify`);
        await fetchFormalities();
        return { ok: true };
      } catch (e) {
        return { ok: false, code: e?.response?.status || 0, msg: e?.message };
      }
    };
    // Phase 6 — button handlers wired to the map popup (formalities fiche
    // was migrated from the sidebar to the popup). They kick the async
    // generate / verify pipelines and update the button label so the user
    // sees feedback without leaving the popup.
    window.__biFormalityPopupRefresh = async (code) => {
      const btn = document.querySelector('[data-testid="formalities-refresh-btn"]');
      const setBtn = (label, disabled = true) => {
        if (!btn) return;
        btn.disabled = disabled;
        btn.textContent = label;
      };
      const kick = await window.__biGenerateFormality(code);
      if (!kick.ok && kick.code !== 409) {
        setBtn("↻ " + (lang === "fr" ? "Échec" : "Failed"), false);
        return;
      }
      setBtn("↻ " + (lang === "fr" ? "Rafraîchissement…" : "Refreshing…"));
      // Poll status until done — up to ~6 min
      for (let i = 0; i < 120; i++) {
        await new Promise((res) => setTimeout(res, 3000));
        try {
          const st = await api.get(`/formalities/${code}/generate/status`);
          if (st.data?.state === "done") {
            await fetchFormalities();
            setBtn("✓ " + (lang === "fr" ? "Rafraîchie" : "Refreshed"), false);
            break;
          }
          if (st.data?.state === "error") {
            setBtn("↻ " + (lang === "fr" ? "Échec" : "Failed"), false);
            break;
          }
        } catch (_) { /* transient */ }
      }
    };
    window.__biFormalityPopupVerify = async (code) => {
      const btn = document.querySelector('[data-testid="formalities-verify-btn"]');
      if (btn) btn.disabled = true;
      const r = await window.__biVerifyFormality(code);
      if (!r?.ok) {
        if (btn) {
          btn.disabled = false;
          btn.textContent = "✓ " + (lang === "fr" ? "Échec" : "Failed");
        }
        return;
      }
      // Refetch formalities so the popup rebuilds with status=verifiee (green).
      await fetchFormalities();
    };
    window.__biGenerateImmigration = async (code, nat) => {
      try {
        const r = await api.post(`/formalities/${code}/immigration/${nat}`);
        return { ok: r.status === 202 || r.status === 200 };
      } catch (e) {
        return { ok: false, code: e?.response?.status || 0, msg: e?.message };
      }
    };

    return () => {
      delete window.__biDonate;
      delete window.__biEnrichMarina;
      delete window.__biEnrichProject;
      delete window.__biGenerateFormality;
      delete window.__biVerifyFormality;
      delete window.__biGenerateImmigration;
      delete window.__biFormalityPopupRefresh;
      delete window.__biFormalityPopupVerify;
    };
  }, [fetchMarinas, fetchProjects, fetchFormalities, lang]);

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
    fetchRoute();
    fetchTerritories();
    fetchFormalities();
    const s = setInterval(fetchStatus, 2000);
    const p = setInterval(fetchProjects, 5000);
    const d = setInterval(fetchDonations, 10000);
    const c = setInterval(fetchCategories, 15000);
    // Marinas refresh only when a build might be running — a light 8s poll.
    const m = setInterval(fetchMarinas, 8000);
    return () => { clearInterval(s); clearInterval(p); clearInterval(d); clearInterval(c); clearInterval(m); };
  }, [fetchStatus, fetchProjects, fetchSettings, fetchDonations, fetchCategories, fetchMarinas, fetchRoute, fetchTerritories, fetchFormalities]);

  // Handler passed to MarinasPanel — sets a one-shot fly target consumed by MapView
  const handleFlyToMarina = useCallback((id, lat, lon) => {
    setFlyToMarina({ id, lat, lon, ts: Date.now() });
  }, []);

  // Phase 4A — Handler wired to both the sidebar rows and the map escale
  // markers: opens the formality card for the given territory + centres the
  // map on the escale coordinates.
  const handleSelectEscale = useCallback((escaleName, territoryCode, coord) => {
    setSelectedTerritory(territoryCode);
    setSelectedEscale(escaleName);
    if (coord && Array.isArray(coord)) {
      setFlyToEscale({ name: escaleName, lat: coord[1], lon: coord[0], ts: Date.now() });
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
          />
        )}
        {mode === "formalities" && (
          <FormalitiesPanel
            t={t}
            route={route}
            formalities={formalities}
            territories={territories}
            selectedTerritory={selectedTerritory}
            selectedEscale={selectedEscale}
            onSelectEscale={handleSelectEscale}
            onFormalitiesRefresh={fetchFormalities}
          />
        )}
        <main className="flex-1 relative min-w-0">
          {view === "map" ? (
            <MapView
              mode={mode}
              projects={projects}
              marinas={marinas}
              formalities={formalities}
              territories={territories}
              route={route}
              selectedTerritory={selectedTerritory}
              selectedEscale={selectedEscale}
              onSelectEscale={handleSelectEscale}
              flyToMarina={flyToMarina}
              flyToEscale={flyToEscale}
              funderFilter={funderFilter} searchQuery={searchQuery} t={t}
              basemap={basemap} categories={categories} categoryFilter={categoryFilter}
              maxMarkers={settings?.max_markers || 1000} minZoom={settings?.min_zoom || 2} />
          ) : (
            <AuditView t={t} status={status} refresh={() => { fetchStatus(); fetchProjects(); }} onFormalitiesRefresh={fetchFormalities} />
          )}
        </main>
          {showSettings && (
          <SettingsPanel t={t} lang={lang} mode={mode} settings={settings}
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
