import { useEffect, useRef } from "react";
import L from "leaflet";

import { FALLBACK_COLORS, TILE_URLS, ampStyle, zoneStyle } from "./map/constants";
import { createPanes } from "./map/layerOrder";
import { zonePopupHtml } from "./map/zonePopup";
import useAmpLayer, { popupHtml as ampPopupHtml, ampPointToLayer } from "./map/useAmpLayer";
import useAnchoragesLayer from "./map/useAnchoragesLayer";
import useCapitaineriesLayer from "./map/useCapitaineriesLayer";
import useFormalitiesLayers from "./map/useFormalitiesLayers";
import useMarinasLayer from "./map/useMarinasLayer";
import useNauticalBasemap from "./map/useNauticalBasemap";
import useProjectsLayer from "./map/useProjectsLayer";
import useRouteLayer from "./map/useRouteLayer";
import useScienceLayer from "./map/useScienceLayer";
import useScienceWms, { ensureWmsPanes } from "./map/useScienceWms";
import useClimatologyLayer from "./map/useClimatologyLayer";
import { attachDepthOnPopup } from "./map/depthRow";
import { applyPenRadii, makePointGroup, POPUP_OPTS } from "./map/points";

/**
 * MapView — carte Leaflet persistante, pastilles canvas, sans cluster.
 */
export default function MapView({
  mode = "projects",
  projects,
  marinas,
  capitaineries,
  flyToCapitainerie,
  science,
  flyToScience,
  scienceWms,
  scienceSourceFilter = "argo",
  climoMonth = 1,
  climoFilters = { wind: true, wave: false, current: false, cyclones: true },
  climoWaveStat = "p90",
  onClimoPoint,
  ampLfpFilter = "All",
  anchorages,
  showAnchorages = true,
  poeZones,
  poePorts,
  route,
  onSelectZone,
  flyToMarina,
  flyToZone,
  flyToPoe,
  flyToAmp,
  flyToProject,
  fitRunBounds,
  ampRunId,
  onAmpSites,
  zoneFiche,
  funderFilter,
  searchQuery,
  t,
  minZoom,
  basemap,
  categories,
  categoryFilter,
  mapVisible = true,
  mapRun = null,
}) {
  const mapRef = useRef(null);
  const mapObj = useRef(null);
  const clusterRef = useRef(null);
  const marinaClusterRef = useRef(null);
  const capitainerieClusterRef = useRef(null);
  const capitainerieMarkersById = useRef(new Map());
  const scienceClusterRef = useRef(null);
  const scienceTracksRef = useRef(null);
  const scienceMarkersById = useRef(new Map());
  const anchorClusterRef = useRef(null);
  const formalitiesClusterRef = useRef(null);
  const ampLayerRef = useRef(null);
  const ampLayersById = useRef(new Map());
  const marinaMarkersById = useRef(new Map());
  const projectMarkersById = useRef(new Map());
  const tileRef = useRef(null);
  const zoomingRef = useRef(false);
  const pendingRef = useRef(null);
  const eezLayerRef = useRef(null);
  const eezLayersByMrgid = useRef(new Map());
  const zoneItemsRef = useRef(new Map());
  const poeClusterRef = useRef(null);
  const poeMarkersById = useRef(new Map());
  const poePortsRef = useRef(poePorts);
  poePortsRef.current = poePorts;
  const zoneFicheRef = useRef(zoneFiche);
  zoneFicheRef.current = zoneFiche;
  const basemapRef = useRef(basemap);
  basemapRef.current = basemap;

  const tRef = useRef(t);
  tRef.current = t;
  const onSelectZoneRef = useRef(onSelectZone);
  onSelectZoneRef.current = onSelectZone;

  const colorMap = {};
  (categories || []).forEach((c) => { colorMap[c.name] = c.color; });
  const colorOf = (g) => colorMap[g] || FALLBACK_COLORS[g] || "#00f0ff";

  useEffect(() => {
    if (mapObj.current) return;
    const WORLD = [[-85, -180], [85, 180]];
    const map = L.map(mapRef.current, {
      center: [22, 5],
      zoom: 2,
      zoomSnap: 0.25,
      minZoom: minZoom || 2,
      maxZoom: 18,
      zoomControl: true,
      maxBounds: WORLD,
      maxBoundsViscosity: 1.0,
    });
    tileRef.current = L.tileLayer(TILE_URLS.dark, {
      attribution: "&copy; Esri &copy; OpenStreetMap contributors",
      maxZoom: 16,
      noWrap: true,
      bounds: WORLD,
    });
    if (basemapRef.current !== "sea") {
      tileRef.current.addTo(map);
    }
    const fitMinZoom = () => {
      const mz = Math.max(minZoom || 2, map.getBoundsZoom(WORLD, true));
      map.setMinZoom(mz);
      if (map.getZoom() < mz) map.setZoom(mz, { animate: false });
    };
    fitMinZoom();
    map.on("resize", fitMinZoom);

    createPanes(map);
    ensureWmsPanes(map);
    map.createPane("science-tracks");
    map.getPane("science-tracks").style.zIndex = 450;

    const cluster = makePointGroup();
    const marinaCluster = makePointGroup();
    marinaClusterRef.current = marinaCluster;
    const capitainerieCluster = makePointGroup();
    capitainerieClusterRef.current = capitainerieCluster;
    const scienceCluster = makePointGroup();
    scienceClusterRef.current = scienceCluster;
    const scienceTracks = L.layerGroup();
    scienceTracksRef.current = scienceTracks;
    const anchorCluster = makePointGroup();
    anchorClusterRef.current = anchorCluster;
    const poeCluster = makePointGroup();
    poeClusterRef.current = poeCluster;
    const eezLayer = L.geoJSON(null, {
      style: (feat) => zoneStyle(zoneItemsRef.current.get(feat?.properties?.mrgid)?.status),
      onEachFeature: (feat, lyr) => {
        const mrgid = feat.properties?.mrgid;
        eezLayersByMrgid.current.set(mrgid, lyr);
        lyr.bindPopup(() => zonePopupHtml(mrgid, feat.properties, {
          tRef, zoneItemsRef, zoneFicheRef, poePortsRef,
        }), {
          ...POPUP_OPTS, maxWidth: 360, minWidth: 260, maxHeight: 460,
          className: "bi-formalities-popup",
        });
        lyr.on("click", () => {
          const cb = onSelectZoneRef.current;
          if (typeof cb === "function") cb(mrgid, null);
        });
        lyr.on("mouseover", () => { try { lyr.setStyle({ weight: 2, opacity: 0.95 }); } catch (_) {} });
        lyr.on("mouseout", () => { try { lyr.setStyle(zoneStyle(zoneItemsRef.current.get(mrgid)?.status)); } catch (_) {} });
      },
    });
    eezLayerRef.current = eezLayer;
    const formalitiesGroup = L.layerGroup([eezLayer, poeCluster]);
    formalitiesClusterRef.current = formalitiesGroup;
    const ampLayer = L.geoJSON(null, {
      pane: "amp",
      style: (feat) => ampStyle(feat?.properties?.lfp),
      pointToLayer: (feat, latlng) => ampPointToLayer(feat, latlng, map.getZoom()),
      onEachFeature: (feat, lyr) => {
        const id = feat.properties?.site_id || feat.properties?.id;
        if (id) ampLayersById.current.set(id, lyr);
        lyr.bindPopup(() => ampPopupHtml(feat.properties || {}, tRef.current), {
          ...POPUP_OPTS, maxWidth: 340, minWidth: 240, maxHeight: 420,
          className: "bi-amp-popup",
        });
        lyr.on("mouseover", () => { try { lyr.setStyle({ weight: 2.4, opacity: 1 }); } catch (_) {} });
        lyr.on("mouseout", () => { try { lyr.setStyle(ampStyle(feat?.properties?.lfp)); } catch (_) {} });
      },
    });
    ampLayerRef.current = ampLayer;
    if (mode === "marinas") map.addLayer(marinaCluster);
    else if (mode === "capitaineries") map.addLayer(capitainerieCluster);
    else if (mode === "formalities") map.addLayer(formalitiesGroup);
    else if (mode === "amp") map.addLayer(ampLayer);
    else if (mode === "science") {
      map.addLayer(scienceCluster);
      map.addLayer(scienceTracks);
    } else if (mode !== "climatology") map.addLayer(cluster);

    const allGroups = () => [cluster, marinaCluster, capitainerieCluster, scienceCluster, anchorCluster, poeCluster];
    map.on("zoomstart", () => { zoomingRef.current = true; });
    map.on("zoomend", () => {
      zoomingRef.current = false;
      const z = map.getZoom();
      allGroups().forEach((g) => applyPenRadii(g, z));
      if (pendingRef.current) {
        const fn = pendingRef.current;
        pendingRef.current = null;
        fn();
      }
    });
    attachDepthOnPopup(map, tRef);
    mapObj.current = map;
    clusterRef.current = cluster;
    if (typeof window !== "undefined") {
      window.__biDebug = {
        map, projects: cluster, marinas: marinaCluster, capitaineries: capitainerieCluster,
        science: scienceCluster, scienceTracks, anchorages: anchorCluster,
        formalities: formalitiesGroup, eez: eezLayer, poe: poeCluster, amp: ampLayer,
      };
    }
    // eslint-disable-next-line
  }, [minZoom]);

  const nauticalActive = useNauticalBasemap({ mapObj, tileRef, basemap });

  useEffect(() => {
    if (!mapVisible || !mapObj.current) return;
    const id = setTimeout(() => {
      try { mapObj.current.invalidateSize({ pan: false }); } catch (_) { /* noop */ }
    }, 80);
    return () => clearTimeout(id);
  }, [mapVisible]);

  useRouteLayer(mapObj, tRef, t);
  useMarinasLayer({ mapObj, marinaClusterRef, marinaMarkersById, marinas, tRef });
  useCapitaineriesLayer({
    mapObj, clusterRef: capitainerieClusterRef, markersById: capitainerieMarkersById,
    capitaineries, tRef,
  });
  useAnchoragesLayer({ mapObj, anchorClusterRef, anchorages, tRef });
  useScienceLayer({
    mapObj, clusterRef: scienceClusterRef, tracksLayerRef: scienceTracksRef,
    markersById: scienceMarkersById,
    science, tRef, sourceFilter: scienceSourceFilter,
  });
  useScienceWms({ mapObj, mode, enabled: scienceWms });
  useClimatologyLayer({
    mapObj, mode, month: climoMonth, filters: climoFilters,
    waveStat: climoWaveStat, tRef, onPoint: onClimoPoint,
  });
  useFormalitiesLayers({
    mapObj, eezLayerRef, eezLayersByMrgid, zoneItemsRef, poeClusterRef,
    poeMarkersById,
    mode, poeZones, poePorts, flyToZone, tRef,
  });
  useProjectsLayer({
    mapObj, clusterRef, zoomingRef, pendingRef, markersById: projectMarkersById,
    projects, funderFilter, categoryFilter, searchQuery, colorOf, tRef,
  });
  useAmpLayer({
    mapObj, ampLayerRef, ampLayersById, mode, tRef, onSites: onAmpSites, flyToAmp,
    runId: ampRunId,
    lfpFilter: ampLfpFilter,
  });

  useEffect(() => {
    const map = mapObj.current;
    const proj = clusterRef.current;
    const mar = marinaClusterRef.current;
    const cap = capitainerieClusterRef.current;
    const sci = scienceClusterRef.current;
    const sciTracks = scienceTracksRef.current;
    const anch = anchorClusterRef.current;
    const formCluster = formalitiesClusterRef.current;
    const amp = ampLayerRef.current;
    if (!map || !proj || !mar || !formCluster) return;
    if (map.hasLayer(proj)) map.removeLayer(proj);
    if (map.hasLayer(mar)) map.removeLayer(mar);
    if (cap && map.hasLayer(cap)) map.removeLayer(cap);
    if (sci && map.hasLayer(sci)) map.removeLayer(sci);
    if (sciTracks && map.hasLayer(sciTracks)) map.removeLayer(sciTracks);
    if (anch && map.hasLayer(anch)) map.removeLayer(anch);
    if (map.hasLayer(formCluster)) map.removeLayer(formCluster);
    if (amp && map.hasLayer(amp)) map.removeLayer(amp);
    if (mode === "marinas") {
      map.addLayer(mar);
      if (anch && showAnchorages) map.addLayer(anch);
    } else if (mode === "capitaineries") {
      if (cap) map.addLayer(cap);
    } else if (mode === "science") {
      if (sci) map.addLayer(sci);
      if (sciTracks) map.addLayer(sciTracks);
    } else if (mode === "climatology") {
      /* roses / raster / pistes via useClimatologyLayer */
    } else if (mode === "formalities") {
      map.addLayer(formCluster);
    } else if (mode === "amp") {
      if (amp) map.addLayer(amp);
    } else {
      map.addLayer(proj);
    }
    map.closePopup();
  }, [mode, showAnchorages]);

  useEffect(() => {
    if (!flyToMarina) return;
    const map = mapObj.current;
    if (!map) return;
    const m = marinaMarkersById.current.get(flyToMarina.id);
    map.flyTo([flyToMarina.lat, flyToMarina.lon], Math.max(map.getZoom(), 14), { duration: 0.8 });
    setTimeout(() => { if (m) m.openPopup(); }, 900);
  }, [flyToMarina]);

  useEffect(() => {
    if (!flyToCapitainerie) return;
    const map = mapObj.current;
    if (!map) return;
    const m = capitainerieMarkersById.current.get(flyToCapitainerie.id);
    map.flyTo([flyToCapitainerie.lat, flyToCapitainerie.lon], Math.max(map.getZoom(), 10), { duration: 1.0 });
    setTimeout(() => { if (m) m.openPopup(); }, 1100);
  }, [flyToCapitainerie]);

  useEffect(() => {
    if (!flyToScience) return;
    const map = mapObj.current;
    if (!map || flyToScience.lat == null || flyToScience.lon == null) return;
    const m = scienceMarkersById.current.get(flyToScience.id);
    if (m && typeof m.getBounds === "function") {
      try {
        map.fitBounds(m.getBounds(), { padding: [48, 48], maxZoom: 8, duration: 1.0 });
      } catch (_) {
        map.flyTo([flyToScience.lat, flyToScience.lon], Math.max(map.getZoom(), 7), { duration: 1.0 });
      }
    } else {
      map.flyTo([flyToScience.lat, flyToScience.lon], Math.max(map.getZoom(), 10), { duration: 1.0 });
    }
    setTimeout(() => { if (m) m.openPopup(); }, 1100);
  }, [flyToScience]);

  useEffect(() => {
    if (!flyToPoe) return;
    const map = mapObj.current;
    if (!map || flyToPoe.lat == null || flyToPoe.lon == null) return;
    const m = poeMarkersById.current.get(flyToPoe.id);
    map.flyTo([flyToPoe.lat, flyToPoe.lon], Math.max(map.getZoom(), 9), { duration: 0.8 });
    setTimeout(() => { if (m) m.openPopup(); }, 900);
  }, [flyToPoe]);

  useEffect(() => {
    if (!flyToProject) return;
    const map = mapObj.current;
    if (!map || flyToProject.lat == null || flyToProject.lon == null) return;
    const m = projectMarkersById.current.get(flyToProject.id);
    map.flyTo([flyToProject.lat, flyToProject.lon], Math.max(map.getZoom(), 10), { duration: 0.7 });
    setTimeout(() => { if (m) m.openPopup(); }, 800);
  }, [flyToProject]);

  useEffect(() => {
    if (!fitRunBounds?.points?.length) return;
    const map = mapObj.current;
    if (!map) return;
    try {
      if (fitRunBounds.points.length === 1) {
        map.setView(fitRunBounds.points[0], 11, { animate: true });
        return;
      }
      const b = L.latLngBounds(fitRunBounds.points);
      if (b.isValid()) {
        map.fitBounds(b, { padding: [48, 48], maxZoom: 12, animate: true });
      }
    } catch (_) { /* bounds vides */ }
  }, [fitRunBounds]);

  // ---------- Lang change → refresh any currently open popup ----------
  // When the user toggles FR ↔ EN, `popup.update()` re-invokes the
  // bindPopup(fn) content function, which reads tRef.current — the popup is
  // re-rendered in the new language with zero marker rebuild.
  useEffect(() => {
    const map = mapObj.current;
    if (!map) return;
    const popup = map._popup;
    if (popup && typeof popup.update === "function") {
      try { popup.update(); } catch (_) { /* map/popup detached — noop */ }
    }
  }, [t, zoneFiche]);

  const emptyCount = (() => {
    if (!mapRun) return 0;
    if (mode === "projects") return projects?.features?.length || 0;
    if (mode === "marinas") return marinas?.features?.length || 0;
    if (mode === "capitaineries") return capitaineries?.features?.length || 0;
    if (mode === "formalities") return poePorts?.features?.length || 0;
    if (mode === "science") return science?.features?.length || 0;
    if (mode === "climatology") return -1;
    return -1;
  })();

  return (
    <div className="w-full h-full relative">
      <div ref={mapRef} data-testid="map-container" className="w-full h-full" />
      {nauticalActive ? (
        <div
          data-testid="nautical-disclaimer"
          className="absolute z-[1000] bottom-6 left-3 max-w-xs px-3 py-2 text-[11px] leading-snug bg-surface/95 border border-amber-400/50 text-amber-200 rounded-sm shadow-md pointer-events-none"
        >
          <span className="font-bold uppercase tracking-wide">{t("seaMapDisclaimerTitle")}</span>
          {" — "}
          {t("seaMapDisclaimerBody")}
        </div>
      ) : null}
      {mapRun && emptyCount === 0 ? (
        <div
          data-testid="map-run-empty"
          className="absolute z-[1000] top-3 left-1/2 -translate-x-1/2 max-w-md px-3 py-2 text-[11px] leading-snug bg-surface/95 border border-amber-400/50 text-amber-100 rounded-sm shadow-md"
        >
          {t("mapRunEmpty")}
        </div>
      ) : null}
    </div>
  );
}
