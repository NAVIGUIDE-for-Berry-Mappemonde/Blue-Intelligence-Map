import { useCallback, useEffect, useRef, useState } from "react";
import api from "./api";
import { makeT } from "./i18n";
import Header from "./components/Header";
import SwarmPanel from "./components/SwarmPanel";
import MapView from "./components/MapView";
import AuditView from "./components/AuditView";
import SettingsPanel from "./components/SettingsPanel";
import { DonateModal, PaymentReturn } from "./components/Donations";

export default function App() {
  const [lang, setLang] = useState("en");
  const [view, setView] = useState("map");
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
  const [paymentReturn, setPaymentReturn] = useState(window.location.pathname.startsWith("/payment/"));
  const t = makeT(lang);
  const lastTotalRef = useRef(-1);

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

  useEffect(() => {
    window.__biDonate = (id) => {
      setDonateTarget({ id, title: null });
    };
    return () => { delete window.__biDonate; };
  }, []);

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
    const s = setInterval(fetchStatus, 2000);
    const p = setInterval(fetchProjects, 5000);
    const d = setInterval(fetchDonations, 10000);
    return () => { clearInterval(s); clearInterval(p); clearInterval(d); };
  }, [fetchStatus, fetchProjects, fetchSettings, fetchDonations]);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-abyss">
      <Header
        lang={lang} setLang={setLang} view={view} setView={setView}
        showSettings={showSettings} setShowSettings={setShowSettings}
        status={status} t={t} basemap={basemap} setBasemap={setBasemap}
        donations={donations}
      />
      <div className="flex flex-1 min-h-0">
        <SwarmPanel
          t={t} status={status} projects={projects} funders={funders}
          funderFilter={funderFilter} setFunderFilter={setFunderFilter}
          searchQuery={searchQuery} setSearchQuery={setSearchQuery}
          onDonate={(id, title) => setDonateTarget({ id, title })}
          refresh={() => { fetchStatus(); fetchProjects(); }}
        />
        <main className="flex-1 relative min-w-0">
          {view === "map" ? (
            <MapView projects={projects} funderFilter={funderFilter} searchQuery={searchQuery} t={t}
              basemap={basemap}
              maxMarkers={settings?.max_markers || 1000} minZoom={settings?.min_zoom || 2} />
          ) : (
            <AuditView t={t} />
          )}
        </main>
        {showSettings && (
          <SettingsPanel t={t} lang={lang} settings={settings}
            onSaved={fetchSettings} onImported={() => fetchProjects(true)} onClose={() => setShowSettings(false)} />
        )}
      </div>
      {donateTarget && (
        <DonateModal t={t} target={donateTarget} onClose={() => setDonateTarget(null)} />
      )}
      {paymentReturn && (
        <PaymentReturn t={t} onDone={() => { setPaymentReturn(false); fetchDonations(); }} />
      )}
    </div>
  );
}
