/** Cache une liste de runs par mode — un fetch, réutilisé à l'ouverture. */

const cache = new Map();
const inflight = new Map();

export function fetchRunsOnce(mode, loader) {
  if (cache.has(mode)) return Promise.resolve(cache.get(mode));
  if (inflight.has(mode)) return inflight.get(mode);
  const pending = Promise.resolve()
    .then(loader)
    .then((items) => {
      cache.set(mode, items || []);
      inflight.delete(mode);
      return cache.get(mode);
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
