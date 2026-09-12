"""Plafonds RAM pour les caches in-process de naviguide-api (VPS 8 Go)."""
from __future__ import annotations

ROUTE_CACHE_MAX = 64
ZEE_CACHE_MAX_BYTES = 5 * 1024 * 1024
ZEE_RESPONSE_MAX_BYTES = 20 * 1024 * 1024
ZEE_MAX_FEATURES_CAP = 80
ZEE_NO_BBOX_MAX_FEATURES = 20


def lru_set(cache: dict, key, value, max_items: int = ROUTE_CACHE_MAX) -> None:
    """Insert en LRU (dict Python 3.7+ ordonné). Évince la plus ancienne."""
    if key in cache:
        cache.pop(key)
    elif len(cache) >= max_items:
        cache.pop(next(iter(cache)))
    cache[key] = value


def too_large(nbytes: int | None, limit: int = ZEE_RESPONSE_MAX_BYTES) -> bool:
    try:
        n = int(nbytes or 0)
    except (TypeError, ValueError):
        return False
    return n > limit
