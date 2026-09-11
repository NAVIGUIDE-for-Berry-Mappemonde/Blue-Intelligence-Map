/**
 * Shared GeoJSON / JSON GET cache.
 * One in-flight request per URL; later callers reuse the same promise.
 * Polls pass `{ force: true }` to refresh.
 */

const cache = new Map();
const inflight = new Map();

export function fetchJson(url, { force = false, maxAge = 10 * 60 * 1000 } = {}) {
  const now = Date.now();
  if (!force) {
    const hit = cache.get(url);
    if (hit && now - hit.at < maxAge) {
      return Promise.resolve(hit.data);
    }
    const pending = inflight.get(url);
    if (pending) return pending;
  }
  const pending = fetch(url)
    .then(async (r) => {
      const data = await r.json();
      cache.set(url, { at: Date.now(), data });
      inflight.delete(url);
      return data;
    })
    .catch((err) => {
      inflight.delete(url);
      throw err;
    });
  inflight.set(url, pending);
  return pending;
}

export function invalidateJson(urlPrefix) {
  for (const key of [...cache.keys()]) {
    if (key === urlPrefix || key.startsWith(urlPrefix)) cache.delete(key);
  }
}
