import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api, { clearAdminKey, hasAdminKey } from "./api";
import { makeT } from "./i18n";
import Header from "./components/Header";
import SwarmPanel from "./components/SwarmPanel";
import MarinasPanel from "./components/MarinasPanel";
import CapitaineriesPanel from "./components/CapitaineriesPanel";
import FormalitiesPanel from "./components/FormalitiesPanel";
import AmpPanel from "./components/AmpPanel";
import SciencePanel from "./components/SciencePanel";
import ClimatologyPanel from "./components/ClimatologyPanel";
import MapView from "./components/MapView";
import AuditView from "./components/AuditView";
import ReviewView from "./components/ReviewView";
import SettingsPanel from "./components/SettingsPanel";
import ReportModal from "./components/ReportModal";

const RUNS_LIST_EP = {
  projects: "/projects/runs",
  marinas: "/marinas/runs",
  capitaineries: "/capitaineries/runs",
  amp: "/amp/runs",
};

function latLngsFromFc(fc) {
  const pts = [];
  const pushPos = (c) => {
    if (Array.isArray(c) && typeof c[0] === "number" && typeof c[1] === "number") {
      pts.push([c[1], c[0]]);
      return;
    }
    if (Array.isArray(c)) c.forEach(pushPos);
  };
  for (const f of fc?.features || []) {
    if (f?.geometry?.coordinates) pushPos(f.geometry.coordinates);
  }
  return pts;
}

// Read the persisted mode on boot. Default = "projects". (7 modes)
const readInitialMode = () => {
  try {
    const v = localStorage.getItem("bi.mode");
    if (v === "marinas" || v === "projects" || v === "formalities" || v === "capitaineries" || v === "amp" || v === "science" || v === "climatology") return v;
  } catch (_) {
    /* localStorage disabled */
  }
  return "projects";
};

const readInitialLang = () => {
  try {
    const v = localStorage.getItem("bi.lang");
    if (v === "fr" || v === "en") return v;
  } catch (_) { /* disabled */ }
  return "fr";
};

const readInitialBasemap = () => {
  try {
    const v = localStorage.getItem("bi.basemap");
    if (v === "dark" || v === "light" || v === "sea") return v;
  } catch (_) { /* disabled */ }
  return "sea";
};

export default function App() {
  const [lang, setLangRaw] = useState(readInitialLang);
  const setLang = useCallback((l) => {
    setLangRaw(l);
    try { localStorage.setItem("bi.lang", l); } catch (_) { /* ignore */ }
  }, []);
  const [view, setView] = useState("map");
  // Mode admin — Console et Review ne sont visibles qu'après validation de la
  // clé (?admin=<clé> dans l'URL, mémorisée par api.js) par le backend.
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    if (!hasAdminKey()) return;
    api.get("/admin/check")
      .then(() => setIsAdmin(true))
      .catch((e) => {
        if (e?.response?.status === 401) clearAdminKey();
      });
  }, []);
  const [mode, setModeRaw] = useState(readInitialMode());   // 'projects' | 'marinas' | 'capitaineries' | 'formalities' | 'amp' | 'science' | 'climatology'
  const [showSettings, setShowSettings] = useState(false);
  const [status, setStatus] = useState(null);
  const [projects, setProjects] = useState({ type: "FeatureCollection", features: [] });
  const [funders, setFunders] = useState({ total: 0, funders: [] });
  const [funderFilter, setFunderFilter] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");
  const [basemap, setBasemapRaw] = useState(readInitialBasemap);
  const setBasemap = useCallback((v) => {
    setBasemapRaw(v);
    try { localStorage.setItem("bi.basemap", v); } catch (_) { /* ignore */ }
  }, []);
  const [scienceSourceFilter, setScienceSourceFilter] = useState("argo");
  const [ampLfpFilter, setAmpLfpFilter] = useState("All");
  const [flyToProject, setFlyToProject] = useState(null);
  const [settings, setSettings] = useState(null);
  const [showReport, setShowReport] = useState(false);
  const [categories, setCategories] = useState([]);
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [marinas, setMarinas] = useState({ type: "FeatureCollection", features: [] });
  const [flyToMarina, setFlyToMarina] = useState(null); // {id, lat, lon} used as a one-shot signal
  const [capitaineries, setCapitaineries] = useState({ type: "FeatureCollection", features: [] });
  const [flyToCapitainerie, setFlyToCapitainerie] = useState(null);
  // Mode Science — catalogues océano + flotteurs Argo
  const [science, setScience] = useState({ type: "FeatureCollection", features: [] });
  const [flyToScience, setFlyToScience] = useState(null);
  const [scienceWms, setScienceWms] = useState(() => {
    try {
      const raw = localStorage.getItem("bi.scienceWms");
      if (raw) {
        return { bathymetry: false, cables: false, substrate: false, ...JSON.parse(raw) };
      }
    } catch (_) { /* ignore */ }
    return { bathymetry: false, cables: false, substrate: false };
  });
  const toggleScienceWms = useCallback((id, on) => {
    setScienceWms((prev) => {
      const next = { ...prev, [id]: !!on };
      try { localStorage.setItem("bi.scienceWms", JSON.stringify(next)); } catch (_) { /* ignore */ }
      return next;
    });
  }, []);
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
  const [poeZonesLoading, setPoeZonesLoading] = useState(true);
  const [poePorts, setPoePorts] = useState({ type: "FeatureCollection", features: [] });
  const [selectedZone, setSelectedZone] = useState(null);   // mrgid
  const [flyToZone, setFlyToZone] = useState(null);         // {mrgid, bbox, ts}
  const [zoneFiche, setZoneFiche] = useState(null);
  const [ficheLoading, setFicheLoading] = useState(false);
  const [mapEpoch, setMapEpoch] = useState(0);
  const [flyToPoe, setFlyToPoe] = useState(null);
  const [ampSites, setAmpSites] = useState({ type: "FeatureCollection", features: [] });
  const [flyToAmp, setFlyToAmp] = useState(null);
  // Sélecteur de run (bouton " > " de l'onglet Map) — { [mode]: {id,label} | null }.
  // Quand un run est sélectionné, la carte affiche ses données au lieu du live.
  const [mapRuns, setMapRuns] = useState({});
  const mapRunsRef = useRef(mapRuns);
  mapRunsRef.current = mapRuns;
  const userPickedRunRef = useRef({});
  const lastFitKeyRef = useRef("");
  const [fitRunBounds, setFitRunBounds] = useState(null);
  // Phase 7bis stabilisation — memoise `t` so its reference stays stable
  // across selection setStates. Otherwise every `handleSelectEscale` call
  // creates a fresh `t` → MapView props change → the formalities marker
  // rebuild useEffect re-fires and the DOM briefly drops to 0 markers.
  const t = useMemo(() => makeT(lang), [lang]);
  const lastTotalRef = useRef(-1);
  const viewRef = useRef(view);
  viewRef.current = view;

  // Sans droits admin, les vues Console (audit) et Review sont inaccessibles.
  useEffect(() => {
    if (!isAdmin && (view === "audit" || view === "review")) setView("map");
  }, [isAdmin, view]);

  // Persist mode + reflect on <html> for CSS var switching
  const setMode = useCallback((m) => {
    lastFitKeyRef.current = "";
    setModeRaw(m);
    try { localStorage.setItem("bi.mode", m); } catch (_) { /* ignore */ }
    if ((m === "science" || m === "climatology") && viewRef.current === "review") setView("map");
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
      const run = mapRunsRef.current.projects;
      if (run?.id) {
        const p = await api.get(`/projects/runs/${run.id}/geojson`);
        setProjects(p.data);
        lastTotalRef.current = -1;   // retour au live => refetch complet
        const n = p.data?.features?.length || 0;
        const key = `projects:${run.id}:${n}`;
        if (n && lastFitKeyRef.current !== key) {
          lastFitKeyRef.current = key;
          const points = latLngsFromFc(p.data);
          if (points.length) setFitRunBounds({ ts: Date.now(), points });
        }
        return;
      }
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

  const marinasRef = useRef(marinas);
  marinasRef.current = marinas;

  const fetchMarinas = useCallback(async (force = false) => {
    try {
      const run = mapRunsRef.current.marinas;
      if (!force && !run?.id
          && (marinasRef.current?.features?.length || 0) > 0) {
        return;
      }
      const { data } = run?.id
        ? await api.get(`/marinas/runs/${run.id}/geojson`, { timeout: 300000 })
        : await api.get("/marinas", { timeout: 300000 });
      setMarinas(data);
      if (run?.id) {
        const n = data?.features?.length || 0;
        const key = `marinas:${run.id}:${n}`;
        if (n && lastFitKeyRef.current !== key) {
          lastFitKeyRef.current = key;
          const points = latLngsFromFc(data);
          if (points.length) setFitRunBounds({ ts: Date.now(), points });
        }
      }
    } catch (e) { /* transient */ }
  }, []);

  const capitaineriesRef = useRef(capitaineries);
  capitaineriesRef.current = capitaineries;

  const fetchCapitaineries = useCallback(async (force = false) => {
    try {
      const run = mapRunsRef.current.capitaineries;
      if (!force && !run?.id && (capitaineriesRef.current?.features?.length || 0) > 0) return;
      const { data } = run?.id
        ? await api.get(`/capitaineries/runs/${run.id}/geojson`)
        : await api.get("/capitaineries");
      setCapitaineries(data);
      if (run?.id) {
        const n = data?.features?.length || 0;
        const key = `capitaineries:${run.id}:${n}`;
        if (n && lastFitKeyRef.current !== key) {
          lastFitKeyRef.current = key;
          const points = latLngsFromFc(data);
          if (points.length) setFitRunBounds({ ts: Date.now(), points });
        }
      }
    } catch (e) { /* transient */ }
  }, []);

  // Phase 8 — anchorages fetcher
  const fetchAnchorages = useCallback(async () => {
    try {
      const { data } = await api.get("/anchorages");
      setAnchorages(data);
    } catch (e) { /* transient */ }
  }, []);

  // Mode Science — le GeoJSON vient de la collection live science_items
  // (moisson non destructive) ; pas de variante par run ni de filtre review.
  const fetchScience = useCallback(async () => {
    try {
      const { data } = await api.get("/science");
      setScience(data);
    } catch (e) { /* transient */ }
  }, []);

  const fetchPoeZones = useCallback(async () => {
    try {
      const { data } = await api.get("/poe/zones");
      setPoeZones(data);
    } catch (e) { /* transient */ }
    finally { setPoeZonesLoading(false); }
  }, []);

  const poePortsRef = useRef(poePorts);
  poePortsRef.current = poePorts;

  const fetchPoePorts = useCallback(async (force = false) => {
    try {
      const run = mapRunsRef.current.formalities;
      if (!force && !run?.id && (poePortsRef.current?.features?.length || 0) > 0) return;
      const { data } = run?.id
        ? await api.get(`/poe/runs/${run.id}/ports`)
        : await api.get("/poe/ports");
      setPoePorts(data);
    } catch (e) { /* transient */ }
  }, []);

  const refreshMapData = useCallback(() => {
    fetchProjects(true);
    fetchMarinas(true);
    fetchCapitaineries(true);
    fetchPoeZones();
    fetchPoePorts(true);
    setMapEpoch((n) => n + 1);
  }, [fetchProjects, fetchMarinas, fetchCapitaineries, fetchPoeZones, fetchPoePorts]);

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
            await fetchMarinas(true);
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
              await fetchMarinas(true);
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
    fetchMarinas();
    fetchScience();
    // Les 6 connexions HTTP/1.1 de Chrome vers cette origine saturent si
    // on lance tous les dumps en parallèle (marinas ~15 Mo + chunks maplibre).
    const later = setTimeout(() => {
      fetchCategories();
      fetchCapitaineries();
      fetchAnchorages();
      fetchPoeZones();
      fetchPoePorts();
    }, 2500);
    const unlessReview = (fn) => () => {
      if (viewRef.current === "review") return;
      fn();
    };
    const fetchMarinasIfIdle = async () => {
      if (viewRef.current === "review") return;
      if (mapRunsRef.current.marinas?.id) {
        await fetchMarinas(true);
        return;
      }
      if ((marinasRef.current?.features?.length || 0) > 1000) return;
      try {
        const { data } = await api.get("/marinas/build/status", { timeout: 5000 });
        if (data?.running) return;
      } catch (_) {
        return;
      }
      await fetchMarinas();
    };
    // Polls espacés (fluidité) : les GeoJSON complets sont lourds ; les
    // panneaux forcent un refresh ciblé dès qu'un build se termine.
    const s = setInterval(fetchStatus, 4000);
    const p = setInterval(unlessReview(() => fetchProjects()), 30000);
    const c = setInterval(fetchCategories, 60000);
    const m = setInterval(fetchMarinasIfIdle, 180000);
    const cap = setInterval(unlessReview(() => fetchCapitaineries()), 60000);
    const a = setInterval(unlessReview(fetchAnchorages), 120000);
    const sci = setInterval(unlessReview(fetchScience), 180000);
    const z = setInterval(unlessReview(fetchPoeZones), 60000);
    const pp = setInterval(unlessReview(() => fetchPoePorts()), 60000);
    return () => {
      clearTimeout(later);
      clearInterval(s); clearInterval(p); clearInterval(c); clearInterval(m);
      clearInterval(cap); clearInterval(a); clearInterval(sci); clearInterval(z); clearInterval(pp);
    };
  }, [fetchStatus, fetchProjects, fetchSettings, fetchCategories, fetchMarinas, fetchCapitaineries, fetchAnchorages, fetchScience, fetchPoeZones, fetchPoePorts]);

  // Sélection d'un run à afficher (null = carte live) pour le mode courant.
  const handleSelectMapRun = useCallback((run) => {
    userPickedRunRef.current[mode] = true;
    lastFitKeyRef.current = "";
    setMapRuns((prev) => ({ ...prev, [mode]: run || null }));
  }, [mode]);

  // Couche Map par défaut = run isolé du mode (contrat §8). Formalités inchangée.
  useEffect(() => {
    if (mode === "formalities" || mode === "science" || mode === "climatology") return undefined;
    const ep = RUNS_LIST_EP[mode];
    if (!ep) return undefined;
    let alive = true;
    const sync = async () => {
      try {
        let runningId = null;
        if (mode === "marinas") {
          const { data } = await api.get("/marinas/build/status", { timeout: 5000 });
          if (data?.run_id) runningId = data.run_id;
        } else if (mode === "capitaineries") {
          const { data } = await api.get("/capitaineries/build/status", { timeout: 5000 });
          if (data?.run_id) runningId = data.run_id;
        } else if (mode === "amp") {
          const { data } = await api.get("/amp/discover-visit-urls/status", { timeout: 5000 });
          if (data?.run_id) runningId = data.run_id;
        } else if (mode === "projects") {
          const { data } = await api.get("/swarm/status", { timeout: 5000 });
          if (data?.run_id) runningId = data.run_id;
        }
        const { data } = await api.get(ep);
        const items = (data?.items || []).filter((r) => !r.wrote_live);
        const worldItems = items.filter((r) => String(r.label || "").startsWith("test-world"));
        const testItems = items.filter((r) => String(r.label || "").startsWith("test-map-30"));
        const pool = worldItems.length ? worldItems : (testItems.length ? testItems : items);
        const running = runningId && pool.find((r) => r.id === runningId);
        const pick = running || pool.find((r) => r.state === "running") || pool[0];
        if (!alive) return;
        setMapRuns((prev) => {
          if (runningId && prev[mode]?.id !== runningId) {
            return { ...prev, [mode]: { id: runningId, label: running?.label || runningId } };
          }
          if (mode in prev) return prev;
          if (!pick) return prev;
          return { ...prev, [mode]: { id: pick.id, label: pick.label || pick.id } };
        });
      } catch (_) { /* transient */ }
    };
    sync();
    const tmr = setInterval(sync, 4000);
    return () => { alive = false; clearInterval(tmr); };
  }, [mode]);

  useEffect(() => {
    const run = mapRuns.amp;
    if (!run?.id) return;
    const n = ampSites?.features?.length || 0;
    const key = `amp:${run.id}:${n}`;
    if (n && lastFitKeyRef.current !== key) {
      lastFitKeyRef.current = key;
      const points = latLngsFromFc(ampSites);
      if (points.length) setFitRunBounds({ ts: Date.now(), points });
    }
  }, [ampSites, mapRuns]);

  // Changement de run sélectionné => re-fetch immédiat du dataset concerné.
  const prevMapRunsRef = useRef({});
  useEffect(() => {
    const prev = prevMapRunsRef.current;
    const next = mapRuns;
    prevMapRunsRef.current = next;
    const changed = Object.keys({ ...prev, ...next }).filter(
      (k) => (prev[k]?.id || null) !== (next[k]?.id || null),
    );
    if (!changed.length) return;
    if (changed.includes("projects")) fetchProjects(true);
    if (changed.includes("marinas")) fetchMarinas(true);
    if (changed.includes("capitaineries")) fetchCapitaineries(true);
    if (changed.includes("formalities")) fetchPoePorts(true);
    if (changed.includes("amp")) setMapEpoch((n) => n + 1);
  }, [mapRuns, fetchProjects, fetchMarinas, fetchCapitaineries, fetchPoePorts]);

  // Handler passed to MarinasPanel — sets a one-shot fly target consumed by MapView
  const handleFlyToMarina = useCallback((id, lat, lon) => {
    setFlyToMarina({ id, lat, lon, ts: Date.now() });
  }, []);

  const handleFlyToCapitainerie = useCallback((id, lat, lon) => {
    setFlyToCapitainerie({ id, lat, lon, ts: Date.now() });
  }, []);

  const handleFlyToScience = useCallback((id, lat, lon) => {
    setFlyToScience({ id, lat, lon, ts: Date.now() });
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

  const handleFlyToAmp = useCallback((id, lat, lon) => {
    if (lat == null || lon == null) return;
    setFlyToAmp({ id, lat, lon, ts: Date.now() });
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
  }, [selectedZone, mapEpoch]);

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden bg-abyss" data-mode={mode}>
      <Header
        lang={lang} setLang={setLang} view={view} setView={setView}
        showSettings={showSettings} setShowSettings={setShowSettings}
        status={status} t={t} basemap={basemap} setBasemap={setBasemap}
        mode={mode} setMode={setMode}
        mapRun={mapRuns[mode] || null}
        onSelectMapRun={handleSelectMapRun}
        isAdmin={isAdmin}
      />
      <div className="flex flex-1 min-h-0">
        {view !== "review" && mode === "projects" && (
          <SwarmPanel
            t={t} projects={projects} funders={funders}
            funderFilter={funderFilter} setFunderFilter={setFunderFilter}
            searchQuery={searchQuery} setSearchQuery={setSearchQuery}
            categories={categories} categoryFilter={categoryFilter} setCategoryFilter={setCategoryFilter}
            onFlyTo={(id, lat, lon) => setFlyToProject({ id, lat, lon, ts: Date.now() })}
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
        {view !== "review" && mode === "capitaineries" && (
          <CapitaineriesPanel
            t={t}
            capitaineries={capitaineries}
            onFlyTo={handleFlyToCapitainerie}
            onRefresh={fetchCapitaineries}
          />
        )}
        {view !== "review" && mode === "formalities" && (
          <FormalitiesPanel
            t={t}
            zones={poeZones}
            zonesLoading={poeZonesLoading}
            selectedZone={selectedZone}
            onSelectZone={handleSelectZone}
            fiche={zoneFiche}
            ficheLoading={ficheLoading}
            onFlyToPort={handleFlyToPoe}
          />
        )}
        {view !== "review" && mode === "amp" && (
          <AmpPanel
            t={t}
            sites={ampSites}
            lfpFilter={ampLfpFilter}
            onLfpFilter={setAmpLfpFilter}
            onFlyTo={handleFlyToAmp}
          />
        )}
        {view !== "review" && mode === "science" && (
          <SciencePanel
            t={t}
            science={science}
            onFlyTo={handleFlyToScience}
            onRefresh={fetchScience}
            sourceFilter={scienceSourceFilter}
            onSourceFilter={setScienceSourceFilter}
            scienceWms={scienceWms}
            onToggleWms={toggleScienceWms}
          />
        )}
        {view !== "review" && mode === "climatology" && (
          <ClimatologyPanel t={t} />
        )}
        <main className="flex-1 relative min-w-0">
          <div
            className={view === "map" ? "absolute inset-0" : "absolute inset-0 invisible pointer-events-none"}
            aria-hidden={view !== "map"}
          >
            <MapView
              mode={mode}
              projects={projects}
              marinas={marinas}
              capitaineries={capitaineries}
              flyToCapitainerie={flyToCapitainerie}
              science={science}
              flyToScience={flyToScience}
              scienceWms={scienceWms}
              scienceSourceFilter={scienceSourceFilter}
              ampLfpFilter={ampLfpFilter}
              anchorages={anchorages}
              showAnchorages={showAnchorages}
              poeZones={poeZones.items}
              poePorts={poePorts}
              onSelectZone={handleSelectZone}
              flyToMarina={flyToMarina}
              flyToZone={flyToZone}
              flyToPoe={flyToPoe}
              flyToAmp={flyToAmp}
              flyToProject={flyToProject}
              fitRunBounds={fitRunBounds}
              ampRunId={mapRuns.amp?.id || null}
              onAmpSites={setAmpSites}
              zoneFiche={zoneFiche}
              funderFilter={funderFilter} searchQuery={searchQuery} t={t}
              basemap={basemap} categories={categories} categoryFilter={categoryFilter}
              minZoom={settings?.min_zoom || 2}
              mapVisible={view === "map"}
              mapRun={mapRuns[mode] || null} />
          </div>
          {view === "audit" ? (
            <AuditView t={t} lang={lang} mode={mode} status={status} refresh={() => { fetchStatus(); fetchProjects(); }}
              settings={settings} onSettingsSaved={fetchSettings}
              onPoeRefresh={() => { fetchPoeZones(); fetchPoePorts(true); }}
              showAnchorages={showAnchorages} setShowAnchorages={setShowAnchorages}
              anchoragesCount={anchorages?.features?.length || 0} />
          ) : view === "review" ? (
            mode === "science" ? (
              <div className="h-full flex items-center justify-center p-8" data-testid="review-science-placeholder">
                <p className="max-w-md text-center text-sm text-slate-400 leading-relaxed">
                  {t("reviewScienceUnavailable")}
                </p>
              </div>
            ) : mode === "climatology" ? (
              <div className="h-full flex items-center justify-center p-8" data-testid="review-climatology-placeholder">
                <p className="max-w-md text-center text-sm text-slate-400 leading-relaxed">
                  {t("reviewClimatologyUnavailable")}
                </p>
              </div>
            ) : (
              <ReviewView t={t} mode={mode} onMapDirty={refreshMapData} />
            )
          ) : null}
        </main>
          {showSettings && (
          <SettingsPanel t={t} lang={lang} mode={mode} settings={settings}
            isAdmin={isAdmin}
            onSaved={fetchSettings}
            // 2026-08-24 bug-fix — import router-callback receives the mode
            // that was actually imported so we only refresh the affected
            // dataset (never both, to avoid unnecessary re-fetches).
            onImported={(importedMode) => {
              if (importedMode === "marinas") fetchMarinas(true);
              else if (importedMode === "capitaineries") fetchCapitaineries(true);
              else if (importedMode === "science") fetchScience();
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
