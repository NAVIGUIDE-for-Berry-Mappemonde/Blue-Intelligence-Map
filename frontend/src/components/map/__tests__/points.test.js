import { penRadius, POPUP_OPTS } from "../points";

describe("pastilles carte", () => {
  test("le rayon pointe de Bic grandit avec le zoom", () => {
    expect(penRadius(2)).toBeLessThan(penRadius(8));
    expect(penRadius(8)).toBeLessThan(penRadius(14));
    expect(penRadius(2)).toBeLessThan(2);
  });

  test("les popups ne déplacent pas la carte", () => {
    expect(POPUP_OPTS.autoPan).toBe(false);
  });
});
