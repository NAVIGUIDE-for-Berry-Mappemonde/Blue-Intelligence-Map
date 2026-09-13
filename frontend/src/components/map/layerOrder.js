/**
 * Ordre vertical unique des panes de la carte — source de vérité verrouillée.
 *
 * Inspiration Open Waters: Seamap : l'ordre de dessin est charge utile, un test
 * (`__tests__/layerOrder.test.js`) fige la liste pour qu'aucun remaniement ne
 * puisse l'altérer par accident. Repères Leaflet (non modifiables) :
 * tilePane 200 < overlayPane 400 < shadowPane 500 < markerPane 600 <
 * tooltipPane 650 < popupPane 700.
 */
export const LEAFLET_BUILTIN_PANES = {
  tilePane: 200,
  overlayPane: 400,
  shadowPane: 500,
  markerPane: 600,
  tooltipPane: 650,
  popupPane: 700,
};

export const PANES = [
  // Fond vectoriel « Carte marine » (MapLibre GL) — sous les tuiles raster.
  { name: "basemap-gl", zIndex: 190 },
  // Atlas climatologie — entre le fond et la route. pointer-events: none
  // pour ne pas voler les clics (C5 dessinera ici, C1 ne pose aucune couche).
  { name: "climatology-raster", zIndex: 250, pointerEvents: "none" },
  { name: "climatology-vector", zIndex: 260, pointerEvents: "none" },
  // Route NAVIGUIDE — sous les clusters et marqueurs.
  { name: "route", zIndex: 380 },
  // Polygones AMP — au-dessus de l'overlayPane, sous les escales.
  { name: "amp", zIndex: 420 },
  // Escales Formalités — au-dessus de tout sauf les marqueurs.
  { name: "formalities-escales", zIndex: 500 },
];

/** Crée tous les panes personnalisés sur la carte, dans l'ordre verrouillé. */
export function createPanes(map) {
  PANES.forEach(({ name, zIndex, pointerEvents }) => {
    map.createPane(name);
    const pane = map.getPane(name);
    pane.style.zIndex = String(zIndex);
    if (pointerEvents) pane.style.pointerEvents = pointerEvents;
  });
}
