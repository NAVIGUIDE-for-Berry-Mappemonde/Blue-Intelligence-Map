/** Convertit public/route.geojson (source officielle Berry) en segments + stops. */

export function routeFromOfficial(fc) {
  const segments = [];
  const stops = [];
  for (const f of fc?.features || []) {
    const g = f.geometry;
    const p = f.properties || {};
    if (g?.type === "LineString" && g.coordinates?.length >= 2) {
      segments.push({
        from: { name: p.from || "", lat: g.coordinates[0][1], lon: g.coordinates[0][0] },
        to: {
          name: p.to || "",
          lat: g.coordinates[g.coordinates.length - 1][1],
          lon: g.coordinates[g.coordinates.length - 1][0],
        },
        coords: g.coordinates,
        nonMaritime: p.type === "overland",
        officialFallback: true,
      });
    } else if (g?.type === "Point") {
      stops.push({
        name: p.name || "",
        lon: g.coordinates[0],
        lat: g.coordinates[1],
        flag: p.point_type === "escale" ? true : "",
      });
    }
  }
  return { segments, stops };
}

export async function loadOfficialBerryRoute(fetchImpl = fetch) {
  const res = await fetchImpl("/route.geojson");
  if (!res.ok) throw new Error(`route.geojson ${res.status}`);
  const fc = await res.json();
  const parsed = routeFromOfficial(fc);
  if (!parsed.segments.length) throw new Error("route.geojson vide");
  return parsed;
}

export function antimeridianLineCount(fc) {
  return (fc?.features || []).filter(
    (f) => f.properties?.from?.includes("Wallis") && f.properties?.to?.includes("Nouméa"),
  ).length;
}
