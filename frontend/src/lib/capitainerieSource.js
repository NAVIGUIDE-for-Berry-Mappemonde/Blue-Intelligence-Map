/** Libellé de source OSM / SHOM / NOAA (éventuellement combinés). */
export function formatCapitainerieSource(source, t) {
  const raw = String(source || "openstreetmap");
  const parts = raw === "openstreetmap"
    ? ["osm"]
    : raw.replace(/openstreetmap/g, "osm").split("+");
  const label = (part) => {
    if (part === "osm") return t("marinasSourceOSM");
    if (part === "shom") return t("marinasSourceSHOM");
    if (part === "noaa") return t("marinasSourceNOAA");
    return part;
  };
  return parts.map(label).join(" + ");
}
