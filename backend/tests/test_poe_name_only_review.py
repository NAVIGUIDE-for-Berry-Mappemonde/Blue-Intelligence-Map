"""Revue name_only — apply_one / apply_review sans Atlas."""
from __future__ import annotations

import pytest

from app.services.poe_name_only_review import apply_one, apply_review, load_review


class _FakeCol:
    def __init__(self, docs: list[dict] | dict[str, dict]):
        if isinstance(docs, dict):
            self.docs = {k: dict(v) for k, v in docs.items()}
        else:
            self.docs = {d["_id"]: dict(d) for d in docs}
        self.inserted: list[dict] = []

    def find_one(self, q, proj=None):
        if "$or" in q:
            for clause in q["$or"]:
                hit = self.find_one(clause)
                if hit is not None:
                    return hit
            return None
        if "_id" in q:
            return self.docs.get(q["_id"])
        if "dedup_key" in q:
            for d in self.docs.values():
                if d.get("dedup_key") == q["dedup_key"] or d["_id"] == q["dedup_key"]:
                    return d
        return None

    def update_one(self, q, upd, upsert=False):
        doc = self.find_one(q)
        if doc is None:
            return
        if "$set" in upd:
            doc.update(upd["$set"])

    def insert_one(self, doc):
        self.docs[doc["_id"]] = dict(doc)
        self.inserted.append(doc)

    def count_documents(self, q=None):
        return len(self.docs)


class _Ports:
    def __init__(self, n: int = 1280, bump: bool = False):
        self.n = n
        self.bump = bump

    def count_documents(self, q=None):
        v = self.n
        if self.bump:
            self.n += 1
        return v


def test_nouveau_point_sets_gps():
    col = _FakeCol([{"_id": "5677:cassis", "dedup_key": "5677:cassis", "lat": None}])
    out = apply_one(col, {
        "action": "nouveau_point",
        "dedup_key": "5677:cassis",
        "lat": 43.216,
        "lon": 5.537,
        "confidence": "haute",
        "notes": "quai",
    }, "t")
    assert out["ok"] is True
    doc = col.docs["5677:cassis"]
    assert doc["lat"] == 43.216
    assert doc["has_coords"] is True
    assert doc["geocode_source"] == "manual_review"
    assert doc["review_action"] == "nouveau_point"


def test_fusion_adds_observation_and_optional_gps():
    col = _FakeCol([
        {"_id": "8495:marinamarigot", "dedup_key": "8495:marinamarigot",
         "lat": None, "has_coords": False, "seed_sources": ["v1"]},
        {"_id": "8495:marigotbaystmartin", "dedup_key": "8495:marigotbaystmartin",
         "name": "Marigot Bay (St Martin)"},
    ])
    out = apply_one(col, {
        "n": 7,
        "action": "fusion",
        "dedup_key": "8495:marigotbaystmartin",
        "name": "Marigot Bay (St Martin)",
        "fusion_target": "8495:marinamarigot",
        "lat": 18.07,
        "lon": -63.086,
    }, "t")
    assert out["ok"] is True
    src = col.docs["8495:marigotbaystmartin"]
    assert src["review_action"] == "fusion"
    assert src["review_target_dedup_key"] == "8495:marinamarigot"
    tgt = col.docs["8495:marinamarigot"]
    assert tgt["lat"] == 18.07
    assert tgt["has_coords"] is True
    assert "listing" in tgt["seed_sources"]
    assert any(o.get("name") == "Marigot Bay (St Martin)" for o in tgt["observations"])


def test_fusion_does_not_overwrite_existing_gps():
    col = _FakeCol([
        {"_id": "48980:saipan", "dedup_key": "48980:saipan",
         "lat": 15.2, "lon": 145.7, "has_coords": True, "seed_sources": ["v1"]},
        {"_id": "48980:tanapagharboursaipan",
         "dedup_key": "48980:tanapagharboursaipan"},
    ])
    apply_one(col, {
        "action": "fusion",
        "dedup_key": "48980:tanapagharboursaipan",
        "name": "Tanapag Harbour (Saipan)",
        "fusion_target": "48980:saipan",
        "lat": 15.226,
        "lon": 145.719,
    }, "t")
    assert col.docs["48980:saipan"]["lat"] == 15.2
    assert col.docs["48980:saipan"]["lon"] == 145.7


def test_abandonner():
    col = _FakeCol([{"_id": "8384:princeedwardisland",
                     "dedup_key": "8384:princeedwardisland"}])
    out = apply_one(col, {
        "action": "abandonner",
        "dedup_key": "8384:princeedwardisland",
        "notes": "région ZA, pas un port",
    }, "t")
    assert out["ok"] is True
    assert col.docs["8384:princeedwardisland"]["review_action"] == "abandonner"


def test_scinder_attaches_existing_and_inserts_missing():
    col = _FakeCol([
        {"_id": "8419:tyrellbayhillsboroughcarriacou",
         "dedup_key": "8419:tyrellbayhillsboroughcarriacou",
         "name": "Tyrell Bay & Hillsborough (Carriacou)",
         "mrgid": 8419, "zone_name": "Grenada"},
        {"_id": "8419:portofhillsborough",
         "dedup_key": "8419:portofhillsborough",
         "name": "Port of Hillsborough", "mrgid": 8419,
         "lat": 12.48, "lon": -61.45, "has_coords": True,
         "seed_sources": ["v1"]},
    ])
    out = apply_one(col, {
        "action": "scinder",
        "dedup_key": "8419:tyrellbayhillsboroughcarriacou",
        "name": "Tyrell Bay & Hillsborough (Carriacou)",
        "points": [
            {"name": "Port of Hillsborough",
             "dedup_key": "8419:portofhillsborough",
             "lat": 12.48, "lon": -61.45},
            {"name": "Tyrrel Bay Marina", "lat": 12.4621, "lon": -61.486},
        ],
    }, "t")
    assert out["ok"] is True
    parent = col.docs["8419:tyrellbayhillsboroughcarriacou"]
    assert parent["review_action"] == "scinder"
    hills = col.docs["8419:portofhillsborough"]
    assert "listing" in hills["seed_sources"]
    assert hills["lat"] == 12.48
    created = [d for d in col.inserted if "tyrrel" in d["_id"]]
    assert len(created) == 1
    assert created[0]["lat"] == 12.4621
    assert created[0]["geocode_source"] == "manual_review"


def test_corriger_zee_merges_to_existing_target():
    col = _FakeCol([
        {"_id": "8488:christmasislandkiritimati",
         "dedup_key": "8488:christmasislandkiritimati",
         "name": "Christmas Island/Kiritimati", "mrgid": 8488},
        {"_id": "8441:christmasislandport",
         "dedup_key": "8441:christmasislandport",
         "name": "Christmas Island Port", "mrgid": 8441,
         "lat": None, "seed_sources": ["run:x"]},
    ])
    out = apply_one(col, {
        "action": "corriger_zee",
        "dedup_key": "8488:christmasislandkiritimati",
        "name": "Christmas Island/Kiritimati",
        "mrgid_correct": 8441,
        "zone_correcte": "Line Group",
        "new_dedup_key": "8441:christmasislandkiritimati",
        "fusion_target_optional": "8441:christmasislandport",
        "lat": 2.0075,
        "lon": -157.4858,
    }, "t")
    assert out["ok"] is True
    src = col.docs["8488:christmasislandkiritimati"]
    assert src["review_target_dedup_key"] == "8441:christmasislandport"
    assert "8488:christmasislandkiritimati" in col.docs
    tgt = col.docs["8441:christmasislandport"]
    assert tgt["lat"] == 2.0075
    assert tgt["mrgid"] == 8441
    assert "8441:christmasislandkiritimati" not in col.docs


def test_apply_review_raises_if_poe_ports_changes():
    col = _FakeCol([])
    with pytest.raises(RuntimeError, match="poe_ports"):
        apply_review(col, _Ports(1280, bump=True), {"verifications": []})


def test_load_review_has_33():
    review = load_review()
    assert review["mongo_written"] in (False, True)
    assert len(review["verifications"]) == 33
    actions = [v["action"] for v in review["verifications"]]
    assert actions.count("fusion") == 16
    assert actions.count("nouveau_point") == 10
    assert actions.count("scinder") == 5
    assert actions.count("corriger_zee") == 1
    assert actions.count("abandonner") == 1


def test_apply_review_json_all_ok_without_touching_ports():
    review = load_review()
    keys: set[str] = set()
    for item in review["verifications"]:
        keys.add(item["dedup_key"])
        for field in ("fusion_target", "fusion_target_optional", "new_dedup_key"):
            if item.get(field):
                keys.add(item[field])
        for t in item.get("fusion_targets") or []:
            keys.add(t)
        for pt in item.get("points") or []:
            if pt.get("dedup_key"):
                keys.add(pt["dedup_key"])
    docs = []
    for k in keys:
        mid = int(k.split(":")[0])
        docs.append({
            "_id": k, "dedup_key": k, "name": k.split(":", 1)[-1],
            "mrgid": mid, "lat": None, "lon": None, "has_coords": False,
            "seed_sources": ["listing"],
        })
    col = _FakeCol(docs)
    col.docs["48980:saipan"]["lat"] = 15.2
    col.docs["48980:saipan"]["lon"] = 145.7
    col.docs["48980:saipan"]["has_coords"] = True
    ports = _Ports(1280)
    out = apply_review(col, ports, review)
    assert out["applied"] == 33
    assert out["total"] == 33
    assert out["poe_ports"] == 1280
    assert out["wrote_poe_ports"] is False
    assert all(r["ok"] for r in out["results"])
    assert col.docs["5677:cassis"]["lat"] is not None
    assert col.docs["5677:cassis"]["has_coords"] is True
    assert col.docs["8495:marinamarigot"]["lat"] is not None
    assert col.docs["48980:saipan"]["lat"] == 15.2
    assert col.docs["8384:princeedwardisland"]["review_action"] == "abandonner"
    assert col.docs["8488:christmasislandkiritimati"]["review_action"] == "corriger_zee"
    assert col.docs["8441:christmasislandport"]["lat"] == 2.0075
