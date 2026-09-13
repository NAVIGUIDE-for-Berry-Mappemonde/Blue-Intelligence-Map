import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { readStoredLang, STORAGE_KEY } from "./langStorage.js";

describe("langue par défaut", () => {
  it("est le français sans clé stockée", () => {
    const mem = { getItem: () => null };
    assert.equal(readStoredLang(mem), "fr");
  });

  it("respecte une langue déjà choisie", () => {
    const mem = { getItem: (k) => (k === STORAGE_KEY ? "en" : null) };
    assert.equal(readStoredLang(mem), "en");
  });
});
