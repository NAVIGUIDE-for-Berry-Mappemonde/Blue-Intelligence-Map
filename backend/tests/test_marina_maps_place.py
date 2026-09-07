"""Signal fiche Google /maps/place/ — sans API Places, sans scrape."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import marina_maps_place as mp
from app.services.marina_world import slim_feature


MINIMES_PLACE = (
    "https://www.google.com/maps/place/Port+de+plaisance+de+La+Rochelle/"
    "@46.1445053,-1.1676049,17z"
)
SEARCH_URL = (
    "https://www.google.com/maps/search/?api=1&query=Bassin+du+Bout+Blanc+46.14687,-1.16452"
)


def test_is_google_place_url():
    assert mp.is_google_place_url(MINIMES_PLACE) is True
    assert mp.is_google_place_url(SEARCH_URL) is False
    assert mp.is_google_place_url("https://portlarochelle.com") is False
    assert mp.is_google_place_url("") is False


def test_pick_minimes_place_rejects_search_and_restaurant():
    hits = [
        {"url": SEARCH_URL, "title": "Bassin du Bout Blanc"},
        {"url": "https://www.google.com/maps/place/Restaurant+Minimes/", "title": "Restaurant Minimes"},
        {
            "url": MINIMES_PLACE,
            "title": "Port de plaisance de La Rochelle",
            "snippet": "Port des Minimes — marina à La Rochelle",
        },
    ]
    picked = mp.pick_google_place("Port des Minimes", hits, 46.14676, -1.16606)
    assert picked is not None
    assert "/maps/place/" in picked
    assert "Restaurant" not in picked
    assert mp.pick_google_place("Bassin du Bout Blanc", hits, 46.14687, -1.16452) is None


def test_stored_place_revalidate_drops_town():
    assert mp.stored_place_still_valid({
        "name": "Port des Minimes",
        "lat": 46.14676,
        "lon": -1.16606,
        "maps_place_url": (
            "https://www.google.com/maps/place/Port+Des+Minimes/"
            "@46.1445053,-1.1676049,17z"
        ),
    }) is True
    assert mp.stored_place_still_valid({
        "name": "Port de La Faute-sur-mer",
        "lat": 46.33,
        "lon": -1.32,
        "maps_place_url": "https://www.google.com/maps/place/La+Faute-sur-Mer/@46.331,-1.321,12z",
    }) is False


def test_rejects_town_and_bridge_place_pages():
    town = {
        "url": "https://www.google.com/maps/place/La+Faute-sur-Mer/@46.331,-1.321,12z",
        "title": "La Faute-sur-Mer",
        "snippet": "La Faute-sur-Mer",
    }
    bridge = {
        "url": "https://www.google.com/maps/place/Passerelle+du+Bassin+des+Chalutiers/",
        "title": "Passerelle du Bassin des Chalutiers",
        "snippet": "Bassin des Chalutiers",
    }
    assert mp.pick_google_place("Port de La Faute-sur-mer", [town], 46.33, -1.32) is None
    assert mp.pick_google_place("Bassin des Chalutiers", [bridge], 46.15, -1.15) is None


def test_bout_blanc_does_not_inherit_nearby_minimes_place():
    hits = [{
        "url": MINIMES_PLACE,
        "title": "Port de plaisance de La Rochelle",
        "snippet": "Grand port de plaisance prisé aux quais bordés de voiliers",
    }]
    assert mp.pick_google_place("Bassin du Bout Blanc", hits, 46.14687, -1.16452) is None
    assert mp.pick_google_place(
        "Port des Minimes", hits, 46.14676, -1.16606,
    ) is None  # pas de jeton « minimes » dans le hit
    hits[0]["snippet"] = "Port des Minimes, La Rochelle"
    assert mp.pick_google_place("Port des Minimes", hits, 46.14676, -1.16606) is not None


def test_unnamed_is_skipped():
    patch = asyncio.run(mp.resolve_google_place({
        "_id": "way/1", "name": "", "lat": 46.14, "lon": -1.16,
    }))
    assert patch["maps_place_status"] == "skipped_unnamed"
    assert patch["maps_place_url"] is None


def test_osm_tag_place_url_without_search():
    called = {"n": 0}

    async def search(_m):
        called["n"] += 1
        return []

    patch = asyncio.run(mp.resolve_google_place({
        "_id": "way/2",
        "name": "Port des Minimes",
        "tags": {"website": MINIMES_PLACE},
    }, search_fn=search))
    assert patch["maps_place_status"] == "found"
    assert patch["maps_place_source"] == "osm_tag"
    assert called["n"] == 0


def test_search_none_stays_none():
    async def search(_m):
        return [{"url": SEARCH_URL, "title": "Bassin du Bout Blanc"}]

    patch = asyncio.run(mp.resolve_google_place({
        "_id": "way/41585114",
        "name": "Bassin du Bout Blanc",
        "lat": 46.14687,
        "lon": -1.16452,
    }, search_fn=search))
    assert patch["maps_place_status"] == "none"
    assert patch["maps_place_url"] is None


def test_search_found_minimes():
    async def search(_m):
        return [{
            "url": MINIMES_PLACE,
            "title": "Port de plaisance de La Rochelle",
            "snippet": "Port des Minimes",
        }]

    patch = asyncio.run(mp.resolve_google_place({
        "_id": "way/741789648",
        "name": "Port des Minimes",
        "lat": 46.14676,
        "lon": -1.16606,
    }, search_fn=search))
    assert patch["maps_place_status"] == "found"
    assert "/maps/place/" in patch["maps_place_url"]


MINIMES_FETCH_PLACE = (
    "https://www.google.com/maps/place/Port+Des+Minimes/"
    "data=!4m7!3m6!1s0x480153ec40a1fe77:0xe993dbf31a0ee44d"
    "!8m2!3d46.1445053!4d-1.1676049!16zL20vMGI4N2Rz"
)


def test_fetch_minimes_exposes_place_bout_blanc_does_not():
    minimes_rec = {
        "title": "Google Maps",
        "final_url": SEARCH_URL.replace("Bassin+du+Bout+Blanc+46.14687,-1.16452", "Port+des+Minimes"),
        "text": "Partial match Port des Minimes 46.14676,-1.16606 Port Des Minimes 4.5 (7,075) Marina",
        "links": [MINIMES_FETCH_PLACE],
    }
    blanc_rec = {
        "title": "Google Maps",
        "final_url": SEARCH_URL,
        "text": "Google Maps can't find Bassin du Bout Blanc 46.14687,-1.16452",
        "links": [],
    }
    hits = mp.place_hits_from_fetch(minimes_rec)
    assert hits and "/maps/place/" in hits[0]["url"]
    picked = mp.pick_google_place("Port des Minimes", hits, 46.14676, -1.16606)
    assert picked and "/maps/place/" in picked
    assert mp.place_hits_from_fetch(blanc_rec) == []
    assert mp.pick_google_place("Bassin du Bout Blanc", hits, 46.14687, -1.16452) is None


def test_resolve_uses_fetch_when_search_empty():
    async def search(_m):
        return []

    async def fetch(marina):
        if marina["name"] == "Port des Minimes":
            return {
                "title": "Google Maps",
                "text": "Port Des Minimes 4.5 Marina",
                "links": [MINIMES_FETCH_PLACE],
            }
        return {
            "title": "Google Maps",
            "text": "Google Maps can't find Bassin du Bout Blanc",
            "links": [],
        }

    found = asyncio.run(mp.resolve_google_place({
        "_id": "way/741789648",
        "name": "Port des Minimes",
        "lat": 46.14676,
        "lon": -1.16606,
    }, search_fn=search, fetch_fn=fetch))
    assert found["maps_place_status"] == "found"
    assert found["maps_place_source"] == "tinyfish_fetch"
    none = asyncio.run(mp.resolve_google_place({
        "_id": "way/41585114",
        "name": "Bassin du Bout Blanc",
        "lat": 46.14687,
        "lon": -1.16452,
    }, search_fn=search, fetch_fn=fetch))
    assert none["maps_place_status"] == "none"
    assert none["maps_place_url"] is None


def test_slim_feature_flags_place():
    feat = slim_feature({
        "_id": "way/741789648",
        "name": "Port des Minimes",
        "lat": 46.14676,
        "lon": -1.16606,
        "maps_place_url": MINIMES_PLACE,
    })
    assert feat["properties"]["has_google_place"] is True
    assert feat["properties"]["maps_place_url"].startswith("https://www.google.com/maps/place/")


class _Cursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    async def to_list(self, n):
        return self.docs[:n]


class _Coll:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, q):
        out = []
        for d in self.docs:
            name = d.get("name")
            if name in ("", None):
                continue
            if d.get("maps_place_status") not in (None,):
                # force=False query uses $or missing/None
                if "maps_place_status" in d and d["maps_place_status"] is not None:
                    continue
            out.append(d)
        return _Cursor(out)

    async def update_one(self, q, upd):
        for d in self.docs:
            if d.get("_id") == q.get("_id"):
                d.update(upd.get("$set") or {})


def test_resolve_batch_signals_without_filtering():
    from app.core.tasks import TaskState

    docs = [
        {"_id": "way/741789648", "name": "Port des Minimes", "lat": 46.14676, "lon": -1.16606},
        {"_id": "way/41585114", "name": "Bassin du Bout Blanc", "lat": 46.14687, "lon": -1.16452},
        {"_id": "node/1", "name": "", "lat": 46.15, "lon": -1.16},
    ]
    coll = _Coll(docs)

    async def search(marina):
        if marina["name"] == "Port des Minimes":
            return [{
                "url": MINIMES_PLACE,
                "title": "Port de plaisance de La Rochelle",
                "snippet": "Port des Minimes",
            }]
        return [{"url": SEARCH_URL, "title": marina["name"]}]

    state = TaskState()
    summary = asyncio.run(mp.resolve_maps_places(
        marinas_coll=coll, state=state, search_fn=search,
    ))
    assert summary["found"] == 1
    assert summary["none"] == 1
    by_id = {d["_id"]: d for d in coll.docs}
    assert by_id["way/741789648"]["maps_place_status"] == "found"
    assert by_id["way/41585114"]["maps_place_status"] == "none"
    assert "maps_place_status" not in by_id["node/1"] or by_id["node/1"].get("maps_place_status") in (None, "skipped_unnamed")
    # On n'a pas filtré : les 3 docs restent.
    assert len(coll.docs) == 3
