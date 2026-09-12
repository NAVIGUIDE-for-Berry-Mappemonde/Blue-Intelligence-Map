import L from "leaflet";

/**
 * Politique d'affichage des popups carte.
 *
 * L'ancienne stratégie (translate CSS du wrapper + timeouts) échouait :
 * `.leaflet-container { overflow: hidden }` clippe la boîte `.leaflet-popup`,
 * `backdrop-filter` sur le wrapper crée un groupe de composition qui reste
 * rogné, et le contenu asynchrone (fiche ZEE, profondeur) arrive après les
 * timeouts. On ne déplace plus la carte (`autoPan: false`).
 *
 * Nouvelle politique :
 * 1. Plafonner largeur/hauteur à l'emprise de la carte (le contenu scrolle).
 * 2. Rester au-dessus du point si l'espace le permet, sinon basculer dessous.
 * 3. Décaler horizontalement toute la popup (pas seulement le wrapper) et
 *    glisser la flèche pour continuer à pointer le point.
 * 4. Recalculer à chaque update / zoom / resize (pas seulement à l'ouverture).
 */

export const POPUP_FIT_PAD = 12;
export const POPUP_FIT_TIP = 22;
export const POPUP_FIT_MIN_H = 96;

export function computePopupFit({
  mapW,
  mapH,
  anchorX,
  anchorY,
  popupW,
  popupH,
  pad = POPUP_FIT_PAD,
  tip = POPUP_FIT_TIP,
  minH = POPUP_FIT_MIN_H,
}) {
  const maxBoxW = Math.max(80, mapW - pad * 2);
  const maxBoxH = Math.max(80, mapH - pad * 2);
  const width = Math.min(Math.max(0, popupW), maxBoxW);
  const height = Math.max(0, popupH);

  const spaceAbove = anchorY - pad - tip;
  const spaceBelow = mapH - anchorY - pad - tip;

  let placeBelow = false;
  let maxH;
  if (height <= spaceAbove) {
    placeBelow = false;
    maxH = Math.min(height, maxBoxH);
  } else if (spaceAbove < minH && spaceBelow > spaceAbove) {
    placeBelow = true;
    maxH = Math.min(height, maxBoxH, Math.max(80, spaceBelow));
  } else {
    placeBelow = false;
    maxH = Math.min(height, maxBoxH, Math.max(80, spaceAbove));
  }

  const minLeft = pad;
  const maxLeft = mapW - pad - width;
  const centered = anchorX - width / 2;
  const left = maxLeft < minLeft
    ? Math.max(0, (mapW - width) / 2)
    : Math.min(Math.max(centered, minLeft), maxLeft);

  const maxTip = Math.max(0, width / 2 - 18);
  const tipShift = Math.max(-maxTip, Math.min(maxTip, anchorX - (left + width / 2)));

  return {
    placeBelow,
    maxWidth: Math.round(maxBoxW),
    maxHeight: Math.round(maxH),
    width: Math.round(width),
    height: Math.round(Math.min(height, maxH)),
    left,
    tipShift,
  };
}

function rememberOrig(popup) {
  if (popup._biMaxWidthOrig == null) {
    popup._biMaxWidthOrig = popup.options.maxWidth || 330;
    popup._biMaxHeightOrig = popup.options.maxHeight || 420;
    popup._biMinWidthOrig = popup.options.minWidth || 50;
  }
}

function capToMap(popup) {
  const map = popup._map;
  if (!map) return;
  rememberOrig(popup);
  const size = map.getSize();
  const innerW = Math.max(80, size.x - POPUP_FIT_PAD * 2);
  const innerH = Math.max(80, size.y - POPUP_FIT_PAD * 2);
  popup.options.maxWidth = Math.min(popup._biMaxWidthOrig, innerW);
  popup.options.minWidth = Math.min(popup._biMinWidthOrig, popup.options.maxWidth);
  popup.options.maxHeight = Math.min(popup._biMaxHeightOrig || innerH, innerH);
}

function applyPlacement(popup, fit, anchor) {
  const el = popup._container;
  const offset = L.point(popup.options.offset || [0, 7]);
  el.classList.toggle("bi-popup--below", fit.placeBelow);
  if (fit.placeBelow) {
    el.style.bottom = "auto";
    el.style.top = `${offset.y}px`;
  } else {
    el.style.top = "auto";
  }
  popup._containerLeft = fit.left - anchor.x;
  el.style.left = `${popup._containerLeft}px`;
}

function clampToMap(popup) {
  const map = popup._map;
  const el = popup._container;
  const mapEl = map.getContainer();
  if (!el || !mapEl) return;
  const mapRect = mapEl.getBoundingClientRect();
  const rect = el.getBoundingClientRect();
  const cs = window.getComputedStyle(el);
  const mt = parseFloat(cs.marginTop) || 0;
  const mb = parseFloat(cs.marginBottom) || 0;
  const pad = POPUP_FIT_PAD;
  const visTop = rect.top - mt;
  const visBottom = rect.bottom + mb;

  let dx = 0;
  let dy = 0;
  if (rect.left < mapRect.left + pad) dx = mapRect.left + pad - rect.left;
  else if (rect.right > mapRect.right - pad) dx = mapRect.right - pad - rect.right;
  if (visTop < mapRect.top + pad) dy = mapRect.top + pad - visTop;
  else if (visBottom > mapRect.bottom - pad) dy = mapRect.bottom - pad - visBottom;

  if (dx) {
    popup._containerLeft += dx;
    el.style.left = `${popup._containerLeft}px`;
  }
  if (dy) {
    if (el.classList.contains("bi-popup--below")) {
      const top = parseFloat(el.style.top) || 0;
      el.style.top = `${top + dy}px`;
    } else {
      popup._containerBottom = (popup._containerBottom || 0) - dy;
      el.style.bottom = `${popup._containerBottom}px`;
    }
  }
}

function shiftTip(popup, anchor) {
  const tipEl = popup._tipContainer;
  const el = popup._container;
  const mapEl = popup._map && popup._map.getContainer();
  if (!tipEl || !el || !mapEl) return;
  const mapRect = mapEl.getBoundingClientRect();
  const rect = el.getBoundingClientRect();
  const centerX = rect.left - mapRect.left + rect.width / 2;
  const maxTip = Math.max(0, rect.width / 2 - 18);
  const tipShift = Math.max(-maxTip, Math.min(maxTip, anchor.x - centerX));
  tipEl.style.left = `calc(50% + ${Math.round(tipShift)}px)`;
}

function fitAfterPosition(popup) {
  const map = popup._map;
  const el = popup._container;
  if (!map || !el || popup._biFitting) return;
  const latlng = popup.getLatLng && popup.getLatLng();
  if (!latlng) return;

  popup._biFitting = true;
  try {
    capToMap(popup);
    origUpdateLayout.call(popup);
    origUpdatePosition.call(popup);

    const size = map.getSize();
    const anchor = map.latLngToContainerPoint(latlng);
    const content = popup._contentNode;
    let popupW = el.offsetWidth || popup._containerWidth || 0;
    let popupH = el.offsetHeight || 0;
    let fit = computePopupFit({
      mapW: size.x,
      mapH: size.y,
      anchorX: anchor.x,
      anchorY: anchor.y,
      popupW,
      popupH,
    });

    const chromeH = content ? Math.max(0, popupH - content.offsetHeight) : 28;
    const chromeW = content ? Math.max(0, popupW - content.offsetWidth) : 32;
    const nextMaxH = Math.max(80, fit.maxHeight - chromeH);
    const nextMaxW = Math.max(80, Math.min(popup.options.maxWidth || fit.maxWidth, fit.maxWidth - chromeW));
    const contentH = content ? content.offsetHeight : popupH;
    const needRelayout = contentH > nextMaxH + 1 || popupW > fit.maxWidth + 1;

    if (needRelayout) {
      popup.options.maxHeight = nextMaxH;
      popup.options.maxWidth = nextMaxW;
      origUpdateLayout.call(popup);
      origUpdatePosition.call(popup);
      popupW = el.offsetWidth || popupW;
      popupH = el.offsetHeight || popupH;
      fit = computePopupFit({
        mapW: size.x,
        mapH: size.y,
        anchorX: anchor.x,
        anchorY: anchor.y,
        popupW,
        popupH,
      });
    }

    popup._biFit = fit;
    applyPlacement(popup, fit, anchor);
    clampToMap(popup);
    shiftTip(popup, anchor);
  } finally {
    popup._biFitting = false;
  }
}

let origUpdateLayout = null;
let origUpdatePosition = null;
let installed = false;

export function installPopupFitPolicy() {
  if (installed) return;
  installed = true;

  const proto = L.Popup.prototype;
  origUpdateLayout = proto._updateLayout;
  origUpdatePosition = proto._updatePosition;
  const origOnRemove = proto.onRemove;

  proto._updateLayout = function patchedPopupLayout() {
    capToMap(this);
    origUpdateLayout.call(this);
  };

  proto._updatePosition = function patchedPopupPosition() {
    if (this._biFitting) {
      origUpdatePosition.call(this);
      return;
    }
    fitAfterPosition(this);
  };

  proto.onRemove = function patchedPopupRemove(map) {
    this._biFit = null;
    return origOnRemove.call(this, map);
  };

  L.Map.addInitHook(function hookPopupFitOnResize() {
    this.on("resize", function refitOpenPopup() {
      const popup = this._popup;
      if (popup && this.hasLayer(popup)) {
        popup._updateLayout();
        popup._updatePosition();
      }
    });
  });
}
