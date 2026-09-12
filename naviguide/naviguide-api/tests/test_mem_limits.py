"""Plafonds RAM NAVIGUIDE — aucun réseau."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mem_limits import (
    ROUTE_CACHE_MAX, ZEE_NO_BBOX_MAX_FEATURES, ZEE_RESPONSE_MAX_BYTES,
    lru_set, too_large,
)


def test_lru_evicts_oldest():
    cache = {}
    for i in range(ROUTE_CACHE_MAX + 5):
        lru_set(cache, i, f"v{i}", max_items=ROUTE_CACHE_MAX)
    assert len(cache) == ROUTE_CACHE_MAX
    assert 0 not in cache
    assert (ROUTE_CACHE_MAX + 4) in cache
    assert 5 in cache


def test_lru_refresh_moves_to_end():
    cache = {}
    lru_set(cache, "a", 1, max_items=2)
    lru_set(cache, "b", 2, max_items=2)
    lru_set(cache, "a", 11, max_items=2)
    lru_set(cache, "c", 3, max_items=2)
    assert "b" not in cache
    assert cache["a"] == 11
    assert cache["c"] == 3


def test_too_large_zee_payload():
    assert too_large(0) is False
    assert too_large(ZEE_RESPONSE_MAX_BYTES) is False
    assert too_large(ZEE_RESPONSE_MAX_BYTES + 1) is True
    assert too_large(None) is False
    assert ZEE_NO_BBOX_MAX_FEATURES < 50
