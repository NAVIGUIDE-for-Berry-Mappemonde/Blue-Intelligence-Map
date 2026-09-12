import L from "leaflet";
import { installPopupFitPolicy } from "./popupFit";

installPopupFitPolicy();

/** Rayon « pointe de Bic » : minuscule en vue monde, un peu plus lisible en zoom. */
export function penRadius(zoom, bump = 0) {
  const z = Number(zoom) || 2;
  let r = 0.7;
  if (z > 3) r = 0.95;
  if (z > 5) r = 1.25;
  if (z > 8) r = 1.8;
  if (z > 12) r = 2.4;
  return Math.max(0.55, r + bump);
}

export const POPUP_OPTS = {
  maxWidth: 330,
  maxHeight: 420,
  autoPan: false,
  autoClose: true,
  closeOnClick: true,
  keepInView: false,
};

/** Groupe de points (plus de cluster) avec addLayers pour les hooks existants. */
export function makePointGroup() {
  // tolerance 8 : la pastille reste minuscule à l'écran mais la zone de
  // clic/tap autour reste confortable (sinon les popups sont inatteignables).
  const renderer = L.canvas({ padding: 0.5, tolerance: 8 });
  const group = L.layerGroup();
  group._biRenderer = renderer;
  group.addLayers = (layers) => {
    (layers || []).forEach((lyr) => group.addLayer(lyr));
    return group;
  };
  return group;
}

export function applyPenRadii(group, zoom) {
  if (!group || typeof group.eachLayer !== "function") return;
  group.eachLayer((lyr) => {
    if (typeof lyr.setRadius !== "function") return;
    const bump = lyr._biBump || 0;
    lyr.setRadius(penRadius(zoom, bump));
  });
}

export function circleOpts(color, {
  zoom = 2, bump = 0, weight = 1, fillOpacity = 0.8, renderer,
} = {}) {
  return {
    radius: penRadius(zoom, bump),
    color,
    weight,
    fillColor: color,
    fillOpacity,
    ...(renderer ? { renderer } : {}),
  };
}
