"""Journal complet d'un run Projets — fichier, Mongo, API, sans écrire `projects`."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import run_journal
from app.services.swarm_pipeline import Swarm


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, n=None):
        if n is None:
            return list(self._docs)
        return list(self._docs[:n])

    def sort(self, *a, **k):
        key = a[0] if a else "seq"
        reverse = (a[1] if len(a) > 1 else 1) == -1
        self._docs.sort(key=lambda d: d.get(key) or 0, reverse=reverse)
        return self

    def skip(self, n):
        return _FakeCursor(self._docs[n:])


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def _match(self, q):
        q = q or {}
        out = []
        for d in self.docs:
            ok = True
            for k, v in q.items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                out.append(d)
        return out

    def find(self, q=None, proj=None):
        return _FakeCursor(self._match(q))

    async def find_one(self, q=None, proj=None):
        docs = self._match(q or {})
        return docs[0] if docs else None

    async def count_documents(self, q=None):
        return len(self._match(q or {}))

    async def insert_one(self, doc):
        self.docs.append(doc)

    async def create_index(self, *a, **k):
        return None


class _FakeDB:
    def __init__(self):
        self._cols = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._cols:
            self._cols[name] = _FakeColl()
        return self._cols[name]


def test_safe_run_id_rejects_path_traversal():
    try:
        run_journal.safe_run_id("../etc/passwd")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_append_and_read_complete_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(run_journal, "RUNS_DIR", tmp_path)
    rid = "20260912-180000-abc123"
    for i in range(12):
        run_journal.append_journal(rid, {
            "kind": "log", "level": "info", "msg": f"line {i}",
        }, seq=i + 1)
    for i in range(15):
        run_journal.append_journal(rid, {
            "kind": "agent", "level": "info", "msg": f"agent {i}",
            "agent": "A001", "engine": "TinyFish N3",
        }, seq=100 + i)
    packed = run_journal.read_journal_file(rid, skip=0, limit=50)
    assert packed["wrote_projects"] is False
    assert packed["total"] == 27
    assert packed["count"] == 27
    agents = run_journal.read_journal_file(rid, kind="agent")
    assert agents["total"] == 15
    text = run_journal.journal_to_text(rid)
    assert "line 0" in text
    assert "agent 14" in text
    assert "wrote_projects: false" in text
    assert (tmp_path / f"{rid}.journal.jsonl").is_file()
    assert (tmp_path / f"{rid}.swarm.jsonl").is_file()
    swarm_lines = (tmp_path / f"{rid}.swarm.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(swarm_lines) == 12  # logs only, not agent lines


def test_legacy_swarm_jsonl_is_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(run_journal, "RUNS_DIR", tmp_path)
    rid = "20260912-150921-6e2088"
    path = tmp_path / f"{rid}.swarm.jsonl"
    path.write_text(
        json.dumps({"ts": "2026-09-12T15:09:21Z", "msg": "MasterSeeds loaded: 21 portals", "level": "info"})
        + "\n",
        encoding="utf-8",
    )
    packed = run_journal.read_journal_file(rid)
    assert packed["total"] == 1
    assert packed["items"][0]["kind"] == "log"
    assert "21 portals" in packed["items"][0]["msg"]
    assert packed["source"] == "file"


def test_tail_returns_last_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(run_journal, "RUNS_DIR", tmp_path)
    rid = "20260912-181111-tail01"
    for i in range(10):
        run_journal.append_journal(rid, {"kind": "log", "msg": f"n{i}"}, seq=i + 1)
    packed = run_journal.read_journal_file(rid, limit=3, tail=True)
    assert [e["msg"] for e in packed["items"]] == ["n7", "n8", "n9"]
    assert packed["skip"] == 7


def test_swarm_agent_logs_not_truncated_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(run_journal, "RUNS_DIR", tmp_path)
    db = _FakeDB()
    sw = Swarm(db)
    sw.run_id = "20260912-182222-agt001"
    aid = sw.new_agent("TinyFish N3", "discover", "https://example.org/projects", "Ocean")
    for i in range(20):
        sw.agent_log(aid, f"progress {i}")
    assert len(sw.agents[aid]["logs"]) == 8
    packed = run_journal.read_journal_file(sw.run_id, kind="agent")
    assert packed["total"] == 20
    assert packed["items"][-1]["msg"] == "progress 19"
    sw.log("Isolated run — wrote_projects: false", "info")
    logs = run_journal.read_journal_file(rid := sw.run_id, kind="log")
    assert logs["total"] == 1
    assert packed["wrote_projects"] is False
    assert db.projects.docs == []


def test_load_journal_mongo_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(run_journal, "RUNS_DIR", tmp_path)
    db = _FakeDB()
    rid = "20260912-183333-mongo1"

    async def go():
        await run_journal.mongo_insert_journal(db, {
            "run_id": rid, "seq": 1, "kind": "log", "msg": "from mongo",
            "ts": "2026-09-12T18:00:00Z",
        })
        packed = await run_journal.load_journal(db, rid)
        return packed

    packed = asyncio.run(go())
    assert packed["source"] == "mongo"
    assert packed["total"] == 1
    assert packed["items"][0]["msg"] == "from mongo"
    assert packed["wrote_projects"] is False


def test_router_exposes_journal():
    from app.routers import project_runs as pr
    paths = {getattr(r, "path", "") for r in pr.router.routes}
    assert "/api/projects/runs/{run_id}/journal" in paths


def _snapshot_params(**extra):
    from app.core.run_rules import attach_rules, snapshot_for_run
    from app.services.run_fingerprint import merge_run_params
    rules = snapshot_for_run(mode="projects", settings={})
    params = attach_rules(merge_run_params({
        "mode": "full",
        "label": "from-scratch-all",
        "force_rescan": True,
        "wrote_projects": False,
        "profile": rules["profile"],
        "openrouter_api_key": "sk-secret-must-not-leak",
        **extra,
    }, {
        "git_sha": "deadbeefcafebabe",
        "git_dirty": False,
        "tinyfish_configured": True,
        "serper_configured": False,
        "openrouter_configured": True,
        "nvidia_configured": False,
        "claude_enabled": False,
        "openrouter_api_key": "also-secret",
    }), rules)
    return params


def test_public_params_strip_secrets_and_keep_rules():
    params = _snapshot_params()
    pub = run_journal.public_run_params(params)
    blob = json.dumps(pub)
    assert "sk-secret" not in blob
    assert "also-secret" not in blob
    assert "api_key" not in blob
    assert pub["wrote_projects"] is False
    assert pub["profile"]
    assert pub["rules"]["shared.no_snap"]["value"] is True
    assert "projects.max_partner_orgs" in pub["rules"]
    again = run_journal.public_run_params(pub)
    assert again["rules"]["shared.no_snap"]["value"] is True
    assert again["profile"] == pub["profile"]


def test_journal_txt_starts_with_params_and_rules():
    params = _snapshot_params()
    items = [
        {"kind": "meta", "msg": "Run params", "params": run_journal.public_run_params(params),
         "ts": "2026-09-12T19:00:00Z"},
        {"kind": "log", "level": "info", "msg": "Isolated run — wrote_projects: false",
         "ts": "2026-09-12T19:00:01Z"},
    ]
    text = run_journal.journal_to_text("20260912-190000-txt001", items)
    assert "# --- Paramètres ---" in text
    assert "# --- Règles" in text
    assert "shared.no_snap" in text
    assert "max_partner_orgs" in text
    assert "from-scratch-all" in text
    assert "wrote_projects: false" in text
    assert "sk-secret" not in text
    assert "Isolated run" in text
    assert "# --- Récit ---" in text
    # la ligne meta n'est pas rejouée dans le flux horodaté
    assert "19:00:00 INFO" not in text


def test_header_reconstructed_from_mongo_params_without_meta():
    params = _snapshot_params()
    items = [{"kind": "log", "msg": "hello old run", "ts": "2026-09-12T18:00:00Z",
              "level": "info"}]
    text = run_journal.journal_to_text("legacy-run", items, params=params)
    assert "hello old run" in text
    assert "shared.no_snap" in text
    assert "sk-secret" not in text
    packed = {"items": items, "total": 1, "wrote_projects": False}
    run_journal.enrich_journal_payload(packed, params)
    assert packed["params"]["wrote_projects"] is False
    assert packed["header_text"]
    assert "cdc_default" in packed["header_text"] or packed["params"]["profile"]
    assert packed["params"]["rules"]["shared.no_snap"]["value"] is True
    # tail=true : items sans meta, l'en-tête reste présent
    tail = {"items": [{"kind": "log", "msg": "late line"}], "total": 50}
    run_journal.enrich_journal_payload(tail, params)
    assert "shared.no_snap" in tail["header_text"]
    jsonl = run_journal.journal_to_jsonl(items, params=params)
    assert '"kind": "meta"' in jsonl or '"kind":"meta"' in jsonl
    assert "sk-secret" not in jsonl


def test_swarm_writes_meta_header_after_seq_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(run_journal, "RUNS_DIR", tmp_path)
    db = _FakeDB()
    rid = "20260912-190000-hdr001"
    params = _snapshot_params()

    async def go():
        await db.project_runs.insert_one({
            "_id": rid, "params": params, "wrote_projects": False,
        })
        sw = Swarm(db)
        sw.run_id = rid
        sw._journal_seq = 0
        await sw._write_journal_header()
        sw.log("Isolated run — wrote_projects: false")
        return sw

    sw = asyncio.run(go())
    packed = run_journal.read_journal_file(rid)
    assert packed["wrote_projects"] is False
    assert packed["items"][0]["kind"] == "meta"
    assert packed["items"][0]["seq"] == 1
    assert packed["items"][1]["kind"] == "log"
    assert packed["items"][1]["seq"] == 2
    blob = json.dumps(packed["items"][0])
    assert "sk-secret" not in blob
    assert "api_key" not in blob
    assert packed["items"][0]["params"]["rules"]["shared.no_snap"]["value"] is True
    text = run_journal.journal_to_text(rid)
    assert "# --- Paramètres ---" in text
    assert "shared.no_snap" in text
    swarm_lines = (tmp_path / f"{rid}.swarm.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(swarm_lines[0])["kind"] == "meta"
    assert db.projects.docs == []
    assert sw.wrote_projects is False
