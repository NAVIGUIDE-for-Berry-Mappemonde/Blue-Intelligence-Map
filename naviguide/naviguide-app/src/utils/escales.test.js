import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { nextEscaleIndex, nextEscaleStop } from "./escales.js";

const stops = [
  { name: "La Rochelle", flag: "fr" },
  { name: "Point intermédiaire Avant Corse", flag: "" },
  { name: "Ajaccio (Corse)", flag: "corse" },
  { name: "Point intermédiaire Après Corse", flag: "" },
];

describe("nextEscaleIndex", () => {
  it("garde une escale", () => {
    assert.equal(nextEscaleIndex(stops, 0), 0);
    assert.equal(nextEscaleIndex(stops, 2), 2);
  });

  it("saute un point intermédiaire vers l'escale suivante", () => {
    assert.equal(nextEscaleIndex(stops, 1), 2);
    assert.equal(nextEscaleStop(stops, 1).stop.name, "Ajaccio (Corse)");
  });

  it("reste sur le dernier intermédiaire s'il n'y a plus d'escale", () => {
    assert.equal(nextEscaleIndex(stops, 3), 3);
  });
});
