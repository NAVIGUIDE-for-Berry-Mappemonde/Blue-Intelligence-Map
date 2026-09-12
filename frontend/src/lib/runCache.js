/**
 * Cache la liste des runs par mode — un fetch, réutilisé à chaque ouverture
 * du sélecteur. Invalidé quand un run est lancé depuis la Console, et
 * rafraîchi tout seul au bout de MAX_AGE_MS (les états done/failed suivent).
 */

const MAX_AGE_MS = 5 * 60 * 1000;

const cache = new Map();
const inflight = new Map();

export function fetchRunsOnce(mode, loader) {
  const hit = cache.get(mode);
  if (hit && Date.now() - hit.at < MAX_AGE_MS) return Promise.resolve(hit.items);
  if (inflight.has(mode)) return inflight.get(mode);
  const pending = Promise.resolve()
    .then(loader)
    .then((items) => {
      cache.set(mode, { at: Date.now(), items: items || [] });
      inflight.delete(mode);
      return items || [];
    })
    .catch((err) => {
      inflight.delete(mode);
      throw err;
    });
  inflight.set(mode, pending);
  return pending;
}

export function invalidateRuns(mode) {
  if (mode) cache.delete(mode);
  else cache.clear();
}
