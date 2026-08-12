import { useCallback, useEffect, useState } from "react";
import api from "./api";
import { makeT } from "./i18n";
import Header from "./components/Header";
import SwarmPanel from "./components/SwarmPanel";
import MapView from "./components/MapView";
import AuditView from "./components/AuditView";
import SettingsPanel from "./components/SettingsPanel";

export default function App() {
  const [lang, setLang] = useState("en");
  const [view, setView] = useState("map");
  const [showSettings, setShowSettings] = useState(false);
  const [status, setStatus] = useState(null);
  const [projects, setProjects] = useState({ type: "FeatureCollection", features: [] });
  const [funders, setFunders] = useState({ total: 0, funders: [] });
  const [funderFilter, setFunderFilter] = useState("All");
  const [settings, setSettings] = useState(null);
  const t = makeT(lang);

  const fetchStatus = useCallback(async () => {
    try {
      const { data } = await api.get("/swarm/status");
      setStatus(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchProjects = useCallback(async () => {
    try {
      const [p, f] = await Promise.all([api.get("/projects"), api.get("/funders")]);
      setProjects(p.data);
      setFunders(f.data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchSettings = useCallback(async () => {
    try {
      const { data } = await api.get("/settings");
      setSettings(data);
    } catch (e) { /* transient */ }
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchProjects();
    fetchSettings();
    const s = setInterval(fetchStatus, 2000);
    const p = setInterval(fetchProjects, 5000);
    return () => { clearInterval(s); clearInterval(p); };
  }, [fetchStatus, fetchProjects, fetchSettings]);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-abyss">
      <Header
        lang={lang} setLang={setLang} view={view} setView={setView}
        showSettings={showSettings} setShowSettings={setShowSettings}
        status={status} t={t}
      />
      <div className="flex flex-1 min-h-0">
        <SwarmPanel
          t={t} status={status} projects={projects} funders={funders}
          funderFilter={funderFilter} setFunderFilter={setFunderFilter}
          refresh={() => { fetchStatus(); fetchProjects(); }}
        />
        <main className="flex-1 relative min-w-0">
          {view === "map" ? (
            <MapView projects={projects} funderFilter={funderFilter} t={t}
              maxMarkers={settings?.max_markers || 1000} minZoom={settings?.min_zoom || 2} />
          ) : (
            <AuditView t={t} />
          )}
        </main>
        {showSettings && (
          <SettingsPanel t={t} lang={lang} settings={settings}
            onSaved={fetchSettings} onClose={() => setShowSettings(false)} />
        )}
      </div>
    </div>
  );
}
