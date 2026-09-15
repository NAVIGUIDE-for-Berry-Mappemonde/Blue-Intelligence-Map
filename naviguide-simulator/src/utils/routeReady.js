/** Route complète : toutes les jambes sont là. Pas un bout Saint-Maur. */
export function isRouteReady(segProgress) {
  const done = Number(segProgress?.done) || 0;
  const total = Number(segProgress?.total) || 0;
  return total > 0 && done >= total;
}
