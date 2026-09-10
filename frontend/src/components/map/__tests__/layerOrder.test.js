/**
 * Verrouillage de l'ordre des couches et du registre des fonds de carte.
 *
 * Inspiration Open Waters: Seamap (`style/index.test.ts`) : l'ordre de dessin
 * est charge utile — un remaniement accidentel doit casser ce test, jamais
 * passer inaperçu en revue.
 */
import { LEAFLET_BUILTIN_PANES, PANES, createPanes } from "../layerOrder";
import { BASEMAPS, BASEMAP_CYCLE, nextBasemap, stripUnavailableSources } from "../basemaps";

describe("ordre des panes (verrouillé)", () => {
  test("la liste exacte des panes ne bouge pas sans casser ce test", () => {
    expect(PANES.map((p) => `${p.name}@${p.zIndex}`)).toEqual([
      "basemap-gl@190",
      "route@380",
      "amp@420",
      "formalities-escales@500",
    ]);
  });

  test("empilement strictement croissant, cohérent avec les panes Leaflet", () => {
    const zs = PANES.map((p) => p.zIndex);
    const sorted = [...zs].sort((a, b) => a - b);
    expect(zs).toEqual(sorted);
    expect(new Set(zs).size).toBe(zs.length);

    const z = Object.fromEntries(PANES.map((p) => [p.name, p.zIndex]));
    // Le fond carte marine reste SOUS les tuiles raster.
    expect(z["basemap-gl"]).toBeLessThan(LEAFLET_BUILTIN_PANES.tilePane);
    // La route NAVIGUIDE au-dessus des tuiles, sous l'overlayPane.
    expect(z.route).toBeGreaterThan(LEAFLET_BUILTIN_PANES.tilePane);
    expect(z.route).toBeLessThan(LEAFLET_BUILTIN_PANES.overlayPane);
    // AMP au-dessus de l'overlayPane, escales au-dessus des AMP.
    expect(z.amp).toBeGreaterThan(LEAFLET_BUILTIN_PANES.overlayPane);
    expect(z["formalities-escales"]).toBeGreaterThan(z.amp);
    // Tout reste sous les marqueurs (et donc sous les popups).
    PANES.forEach((p) => {
      expect(p.zIndex).toBeLessThan(LEAFLET_BUILTIN_PANES.markerPane);
    });
  });

  test("createPanes applique les zIndex sur la carte", () => {
    const panes = {};
    const fakeMap = {
      createPane: (name) => { panes[name] = { style: {} }; },
      getPane: (name) => panes[name],
    };
    createPanes(fakeMap);
    PANES.forEach((p) => {
      expect(panes[p.name].style.zIndex).toBe(String(p.zIndex));
    });
  });
});

describe("registre des fonds de carte (verrouillé)", () => {
  test("exactement trois fonds : dark, light, sea", () => {
    expect(Object.keys(BASEMAPS)).toEqual(["dark", "light", "sea"]);
    expect(BASEMAP_CYCLE).toEqual(["dark", "light", "sea"]);
  });

  test("les fonds raster ont une URL de tuiles https", () => {
    ["dark", "light"].forEach((k) => {
      expect(BASEMAPS[k].kind).toBe("raster");
      expect(BASEMAPS[k].url).toMatch(/^https:\/\//);
    });
  });

  test("la carte marine est un style GL avec attribution et avertissement", () => {
    const sea = BASEMAPS.sea;
    expect(sea.kind).toBe("gl");
    expect(sea.styleUrl).toMatch(/^https:\/\/.*style\.json$/);
    expect(sea.notForNavigation).toBe(true);
    expect(sea.attribution).toContain("Open Waters: Seamap");
    expect(sea.attribution).toContain("CC-BY 4.0");
    expect(sea.attribution).toContain("OpenStreetMap");
  });

  test("le cycle des fonds revient à son point de départ", () => {
    expect(nextBasemap("dark")).toBe("light");
    expect(nextBasemap("light")).toBe("sea");
    expect(nextBasemap("sea")).toBe("dark");
    // valeur inconnue → premier fond du cycle (jamais d'undefined)
    expect(nextBasemap("banana")).toBe("dark");
  });

  test("stripUnavailableSources retire elevation sans toucher aux autres sources", () => {
    const style = {
      sources: { seamap: { type: "vector" }, elevation: { type: "raster-dem" } },
      layers: [
        { id: "sea", source: "seamap" },
        { id: "hill", source: "elevation" },
      ],
    };
    const out = stripUnavailableSources(style);
    expect(out.sources.elevation).toBeUndefined();
    expect(out.sources.seamap).toEqual({ type: "vector" });
    expect(out.layers.map((l) => l.id)).toEqual(["sea"]);
    expect(style.sources.elevation).toBeDefined();
  });
});
