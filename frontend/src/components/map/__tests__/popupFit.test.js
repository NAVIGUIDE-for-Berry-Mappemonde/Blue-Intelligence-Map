import L from "leaflet";
import { computePopupFit, POPUP_FIT_PAD } from "../popupFit";
import { POPUP_OPTS } from "../points";

describe("politique d'affichage des popups", () => {
  test("les popups ne déplacent pas la carte", () => {
    expect(POPUP_OPTS.autoPan).toBe(false);
    expect(POPUP_OPTS.keepInView).toBe(false);
  });

  test("Leaflet repositionne via la politique (plus de translate du wrapper)", () => {
    expect(L.Popup.prototype._updatePosition.name).toBe("patchedPopupPosition");
  });

  test("au centre, la popup reste au-dessus et centrée", () => {
    const fit = computePopupFit({
      mapW: 1000, mapH: 700, anchorX: 500, anchorY: 400,
      popupW: 340, popupH: 280,
    });
    expect(fit.placeBelow).toBe(false);
    expect(fit.left).toBeCloseTo(500 - 340 / 2, 5);
    expect(Math.abs(fit.tipShift)).toBeLessThan(1);
    expect(fit.maxHeight).toBe(280);
  });

  test("trop près du haut, la popup bascule dessous", () => {
    const fit = computePopupFit({
      mapW: 1000, mapH: 700, anchorX: 500, anchorY: 80,
      popupW: 340, popupH: 420,
    });
    expect(fit.placeBelow).toBe(true);
    expect(fit.maxHeight).toBeGreaterThan(300);
    expect(fit.maxHeight).toBeLessThanOrEqual(700 - POPUP_FIT_PAD * 2);
  });

  test("une petite popup près du haut reste au-dessus si elle tient", () => {
    const fit = computePopupFit({
      mapW: 1000, mapH: 700, anchorX: 500, anchorY: 80,
      popupW: 220, popupH: 40,
    });
    expect(fit.placeBelow).toBe(false);
  });

  test("trop près de la droite, la boîte glisse à gauche et la flèche suit", () => {
    const fit = computePopupFit({
      mapW: 1000, mapH: 700, anchorX: 960, anchorY: 400,
      popupW: 340, popupH: 200,
    });
    expect(fit.placeBelow).toBe(false);
    expect(fit.left + fit.width).toBeLessThanOrEqual(1000 - POPUP_FIT_PAD);
    expect(fit.left).toBeGreaterThanOrEqual(POPUP_FIT_PAD);
    expect(fit.tipShift).toBeGreaterThan(0);
  });

  test("trop près de la gauche, la boîte reste dans la carte", () => {
    const fit = computePopupFit({
      mapW: 1000, mapH: 700, anchorX: 40, anchorY: 400,
      popupW: 340, popupH: 200,
    });
    expect(fit.left).toBe(POPUP_FIT_PAD);
    expect(fit.tipShift).toBeLessThan(0);
  });

  test("cas Tunisie (haut-droit) : dessous + décalage gauche, entièrement dans la carte", () => {
    const fit = computePopupFit({
      mapW: 1000, mapH: 700, anchorX: 850, anchorY: 120,
      popupW: 340, popupH: 420,
    });
    expect(fit.placeBelow).toBe(true);
    expect(fit.left).toBeGreaterThanOrEqual(POPUP_FIT_PAD);
    expect(fit.left + fit.width).toBeLessThanOrEqual(1000 - POPUP_FIT_PAD);
    expect(fit.height).toBeLessThanOrEqual(fit.maxHeight);
    expect(fit.maxHeight).toBeLessThanOrEqual(700 - POPUP_FIT_PAD * 2);
  });

  test("une popup plus large que la carte est ramenée à l'emprise", () => {
    const fit = computePopupFit({
      mapW: 320, mapH: 500, anchorX: 160, anchorY: 250,
      popupW: 400, popupH: 180,
    });
    expect(fit.width).toBe(320 - POPUP_FIT_PAD * 2);
    expect(fit.maxWidth).toBe(320 - POPUP_FIT_PAD * 2);
    expect(fit.left).toBe(POPUP_FIT_PAD);
  });

  test("une popup plus haute que la carte est plafonnée", () => {
    const fit = computePopupFit({
      mapW: 800, mapH: 400, anchorX: 400, anchorY: 200,
      popupW: 300, popupH: 900,
    });
    expect(fit.maxHeight).toBeLessThanOrEqual(400 - POPUP_FIT_PAD * 2);
    expect(fit.maxHeight).toBeGreaterThanOrEqual(80);
  });

  test("au milieu, une grande popup se réduit au-dessus plutôt que de basculer", () => {
    const fit = computePopupFit({
      mapW: 1000, mapH: 700, anchorX: 500, anchorY: 350,
      popupW: 340, popupH: 420,
    });
    expect(fit.placeBelow).toBe(false);
    expect(fit.maxHeight).toBeLessThan(420);
    expect(fit.maxHeight).toBeGreaterThan(200);
  });
});
