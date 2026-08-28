import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet.markercluster";

import { FALLBACK_COLORS, TILE_URLS, zoneStyle } from "./map/constants";
import { zonePopupHtml } from "./map/zonePopup";
import useAnchoragesLayer from "./map/useAnchoragesLayer";
import useFormalitiesLayers from "./map/useFormalitiesLayers";
import useMarinasLayer from "./map/useMarinasLayer";
import useProjectsLayer from "./map/useProjectsLayer";
import useRouteLayer from "./map/useRouteLayer";

/**
 * MapView — orchestrateur de la carte Leaflet à monde unique.
 *
 * Initialise la carte, les panes et les clusters, puis délègue chaque couche
 * à son hook dédié (components/map/) : route officielle, projets, marinas,
 * mouillages, ZEE + Ports d'Entrée. Gère la bascule de mode et le flyTo.
 */
export default function MapView({
  mode = "projects",
  projects,
  marinas,
  anchorages,
  showAnchorages = true,
  poeZones,
  poePorts,
  route,
  onSelectZone,
  flyToMarina,
  flyToZone,
  funderFilter,
  searchQuery,
  t,
  maxMarkers,
  minZoom,
  basemap,
  categories,
  categoryFilter,
}) {
  const mapRef = useRef(null);
  const mapObj = useRef(null);
  const clusterRef = useRef(null);
  const marinaClusterRef = useRef(null);
  const anchorClusterRef = useRef(null);
  const formalitiesClusterRef = useRef(null);
  const marinaMarkersById = useRef(new Map());
  const tileRef = useRef(null);
  const zoomingRef = useRef(false);
  const pendingRef = useRef(null);
  // Formalities mode = EEZ polygons + PoE port markers
  const eezLayerRef = useRef(null);
  const eezLayersByMrgid = useRef(new Map());
  const zoneItemsRef = useRef(new Map());
  const poeClusterRef = useRef(null);

  // Popup content must reflect the CURRENT language + zone statuses — bindPopup(fn)
  // reads these refs at open time instead of capturing stale closures.
  const tRef = useRef(t);
  tRef.current = t;
  const onSelectZoneRef = useRef(onSelectZone);
  onSelectZoneRef.current = onSelectZone;

  const colorMap = {};
  (categories || []).forEach((c) => { colorMap[c.name] = c.color; });
  const colorOf = (g) => colorMap[g] || FALLBACK_COLORS[g] || "#00f0ff";

  // ---------- Initialisation de la carte, des panes et des clusters ----------
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
      attribution: '&copy; Esri &copy; OpenStreetMap contributors',
      maxZoom: 16,
      noWrap: true,
      bounds: WORLD,
    }).addTo(map);
    // Single-world view: min zoom = world exactly fills the screen (no grey bands, no wrap)
    const fitMinZoom = () => {
      const mz = Math.max(minZoom || 2, map.getBoundsZoom(WORLD, true));
      map.setMinZoom(mz);
      if (map.getZoom() < mz) map.setZoom(mz, { animate: false });
    };
    fitMinZoom();
    map.on("resize", fitMinZoom);

    // Dedicated Leaflet pane for the route, drawn UNDER the clusters and markers.
    map.createPane("route");
    map.getPane("route").style.zIndex = 380;   // < markerPane (600) & tilePane (200 default)
    map.createPane("formalities-escales");
    map.getPane("formalities-escales").style.zIndex = 500;

    const cluster = L.markerClusterGroup({
      maxClusterRadius: 50,
      chunkedLoading: true,
      chunkInterval: 100,
      removeOutsideVisibleBounds: true,
      animate: false,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster" style="width:34px;height:34px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [34, 34],
      }),
    });
    // Marinas cluster — red-tinted, only added to the map when mode="marinas"
    const marinaCluster = L.markerClusterGroup({
      maxClusterRadius: 40,
      chunkedLoading: true,
      chunkInterval: 100,
      removeOutsideVisibleBounds: true,
      animate: false,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster-marina" style="width:32px;height:32px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [32, 32],
      }),
    });
    marinaClusterRef.current = marinaCluster;
    // Anchorages cluster (teal), shown alongside marinas in marinas mode
    const anchorCluster = L.markerClusterGroup({
      maxClusterRadius: 40,
      chunkedLoading: true,
      chunkInterval: 100,
      removeOutsideVisibleBounds: true,
      animate: false,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster-anchorage" style="width:30px;height:30px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [30, 30],
      }),
    });
    anchorClusterRef.current = anchorCluster;
    // Formalities mode: EEZ choropleth (VLIZ) + PoE cluster. A single
    // layerGroup wraps both so the mode-swap effect keeps a single handle.
    const poeCluster = L.markerClusterGroup({
      maxClusterRadius: 45,
      chunkedLoading: true,
      animate: false,
      iconCreateFunction: (c) => L.divIcon({
        html: `<div class="bi-cluster-formalities" style="width:32px;height:32px;">${c.getChildCount()}</div>`,
        className: "",
        iconSize: [32, 32],
      }),
    });
    poeClusterRef.current = poeCluster;
    const eezLayer = L.geoJSON(null, {
      style: (feat) => zoneStyle(zoneItemsRef.current.get(feat?.properties?.mrgid)?.status),
      onEachFeature: (feat, lyr) => {
        const mrgid = feat.properties?.mrgid;
        eezLayersByMrgid.current.set(mrgid, lyr);
        lyr.bindPopup(() => zonePopupHtml(mrgid, feat.properties, { tRef, zoneItemsRef }), {
          maxWidth: 350, minWidth: 260, maxHeight: 380, autoPan: true, autoPanPadding: [40, 40],
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
    // Add whichever cluster matches the initial mode; the mode-swap effect will fix it up
    // if the user is starting in another mode.
    if (mode === "marinas") map.addLayer(marinaCluster);
    else if (mode === "formalities") map.addLayer(formalitiesGroup);
    else map.addLayer(cluster);
    // Defer any layer rebuild until zoom animation fully ends (prevents orphan clusters / grey screens)
    map.on("zoomstart", () => { zoomingRef.current = true; });
    map.on("zoomend", () => {
      zoomingRef.current = false;
      if (pendingRef.current) {
        const fn = pendingRef.current;
        pendingRef.current = null;
        fn();
      }
      map.invalidateSize({ pan: false });
    });
    // Keep popups fully visible WITHOUT panning the map: shift the popup bubble itself
    const adjustPopup = (popup) => {
      const el = popup.getElement && popup.getElement();
      if (!el || !mapRef.current) return;
      const wrapper = el.querySelector(".leaflet-popup-content-wrapper");
      if (!wrapper) return;
      wrapper.style.transform = "";
      const mapRect = mapRef.current.getBoundingClientRect();
      const rect = wrapper.getBoundingClientRect();
      const pad = 10;
      let dx = 0, dy = 0;
      if (rect.left < mapRect.left + pad) dx = mapRect.left + pad - rect.left;
      else if (rect.right > mapRect.right - pad) dx = mapRect.right - pad - rect.right;
      if (rect.top < mapRect.top + pad) dy = mapRect.top + pad - rect.top;
      else if (rect.bottom > mapRect.bottom - pad) dy = mapRect.bottom - pad - rect.bottom;
      if (dx || dy) {
        wrapper.style.transition = "transform 0.15s ease";
        wrapper.style.transform = `translate(${dx}px, ${dy}px)`;
      }
    };
    map.on("popupopen", (e) => {
      adjustPopup(e.popup);
      setTimeout(() => adjustPopup(e.popup), 250);
      setTimeout(() => adjustPopup(e.popup), 800);
    });
    mapObj.current = map;
    clusterRef.current = cluster;
    // Debug hook — expose the map + all clusters on window for headless
    // inspection. Non-visible, no runtime cost.
    if (typeof window !== "undefined") {
      window.__biDebug = { map, projects: cluster, marinas: marinaCluster, anchorages: anchorCluster, formalities: formalitiesGroup, eez: eezLayer, poe: poeCluster };
    }
    // eslint-disable-next-line
  }, [minZoom]);

  useEffect(() => {
    if (tileRef.current) tileRef.current.setUrl(TILE_URLS[basemap] || TILE_URLS.dark);
  }, [basemap]);

  // ---------- Couches déléguées aux hooks dédiés ----------
  useRouteLayer(mapObj, tRef, t);
  useMarinasLayer({ mapObj, marinaClusterRef, marinaMarkersById, marinas, tRef });
  useAnchoragesLayer({ mapObj, anchorClusterRef, anchorages, tRef });
  useFormalitiesLayers({
    mapObj, eezLayerRef, eezLayersByMrgid, zoneItemsRef, poeClusterRef,
    mode, poeZones, poePorts, flyToZone, tRef,
  });
  useProjectsLayer({
    mapObj, clusterRef, zoomingRef, pendingRef,
    projects, funderFilter, categoryFilter, searchQuery, maxMarkers, colorOf, tRef,
  });

  // ---------- Mode swap: attach the right cluster, hide the others ----------
  useEffect(() => {
    const map = mapObj.current;
    const proj = clusterRef.current;
    const mar = marinaClusterRef.current;
    const anch = anchorClusterRef.current;
    const formCluster = formalitiesClusterRef.current;
    if (!map || !proj || !mar || !formCluster) return;
    // Detach everything first, then attach only the layer(s) for the current mode.
    if (map.hasLayer(proj)) map.removeLayer(proj);
    if (map.hasLayer(mar)) map.removeLayer(mar);
    if (anch && map.hasLayer(anch)) map.removeLayer(anch);
    if (map.hasLayer(formCluster)) map.removeLayer(formCluster);
    if (mode === "marinas") {
      map.addLayer(mar);
      if (anch && showAnchorages) map.addLayer(anch);
    } else if (mode === "formalities") {
      map.addLayer(formCluster);
    } else {
      map.addLayer(proj);
    }
    map.closePopup();
  }, [mode, showAnchorages]);

  // ---------- FlyTo signal from MarinasPanel ----------
  useEffect(() => {
    if (!flyToMarina) return;
    const map = mapObj.current;
    if (!map) return;
    const m = marinaMarkersById.current.get(flyToMarina.id);
    map.flyTo([flyToMarina.lat, flyToMarina.lon], Math.max(map.getZoom(), 10), { duration: 1.0 });
    setTimeout(() => { if (m) m.openPopup(); }, 1100);
  }, [flyToMarina]);

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
  }, [t]);

  return (
    <div className="w-full h-full relative">
      <div ref={mapRef} data-testid="map-container" className="w-full h-full" />
    </div>
  );
}
