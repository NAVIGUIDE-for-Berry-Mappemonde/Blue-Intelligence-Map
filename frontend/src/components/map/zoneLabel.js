/** Libellé d'une ZEE : un polygone VLIZ, jamais un agrégat pays. */

export function zoneDisplayName(z, t) {
  if (!z) return "";
  const sov = z.sovereign || "";
  if (z.disambiguated && sov) {
    const q = z.qualifier || z.name || "";
    let inner = q;
    if (typeof t === "function") {
      if (z.qualifier_key === "hexagone") inner = t("poeZoneHexagone");
      else if (z.qualifier_key === "metropole") inner = t("poeZoneMetropole");
      else if (z.qualifier_key === "joint") {
        inner = q ? `${t("poeZoneJoint")} · ${q}` : t("poeZoneJoint");
      } else if (z.qualifier_key === "overlap") {
        inner = q ? `${t("poeZoneOverlap")} · ${q}` : t("poeZoneOverlap");
      }
    }
    return `${sov} (${inner})`;
  }
  return z.label || z.name || z.geoname || "";
}

export function zoneSubtitle(z) {
  if (!z) return "";
  if (z.disambiguated) {
    const bits = [];
    if (z.iso2) bits.push(z.iso2);
    if (z.pol_type && z.pol_type !== "200NM") bits.push(z.pol_type);
    return bits.join(" · ") || z.geoname || "";
  }
  return z.sovereign || "—";
}

export function zoneSearchHaystack(z) {
  if (!z) return "";
  return [
    z.label, z.name, z.geoname, z.sovereign, z.qualifier, z.iso2, z.sov_iso2,
  ].filter(Boolean).join(" ").toLowerCase();
}
