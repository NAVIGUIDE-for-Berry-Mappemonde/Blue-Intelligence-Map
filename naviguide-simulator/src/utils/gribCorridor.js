/** Couloir bateau seulement — refuse un bbox globe. */
export function corridorBboxOk(bbox) {
  if (!bbox || bbox.length !== 4) return false;
  const [south, north, west, east] = bbox.map(Number);
  if (![south, north, west, east].every(Number.isFinite)) return false;
  return north - south <= 20 && Math.abs(east - west) <= 40;
}

export function pointInBbox(bbox, lat, lon) {
  if (!corridorBboxOk(bbox) || lat == null || lon == null) return false;
  const [south, north, west, east] = bbox.map(Number);
  if (lat < south || lat > north) return false;
  if (west <= east) return lon >= west && lon <= east;
  return lon >= west || lon <= east;
}

/** Bbox serveur si elle contient le bateau, sinon disque local. */
export function corridorForBoat(bbox, lat, lon) {
  if (pointInBbox(bbox, lat, lon)) return bbox.map(Number);
  if (lat == null || lon == null) return corridorBboxOk(bbox) ? bbox.map(Number) : null;
  return [lat - 3, lat + 3, lon - 3.5, lon + 3.5];
}
