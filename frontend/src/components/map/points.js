import L from "leaflet";

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
  const renderer = L.canvas({ padding: 0.5, tolerance: 3 });
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

/** Décale le popup dans le cadre visible sans bouger la carte. */
export function keepPopupInView(map, popup, mapEl) {
  const el = popup && popup.getElement && popup.getElement();
  if (!el || !mapEl) return;
  const wrapper = el.querySelector(".leaflet-popup-content-wrapper") || el;
  wrapper.style.transform = "";
  const mapRect = mapEl.getBoundingClientRect();
  const rect = wrapper.getBoundingClientRect();
  const pad = 12;
  let dx = 0;
  let dy = 0;
  if (rect.left < mapRect.left + pad) dx = mapRect.left + pad - rect.left;
  else if (rect.right > mapRect.right - pad) dx = mapRect.right - pad - rect.right;
  if (rect.top < mapRect.top + pad) dy = mapRect.top + pad - rect.top;
  else if (rect.bottom > mapRect.bottom - pad) dy = mapRect.bottom - pad - rect.bottom;
  if (dx || dy) {
    wrapper.style.transition = "transform 0.12s ease";
    wrapper.style.transform = `translate(${dx}px, ${dy}px)`;
  }
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
