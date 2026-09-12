"""Journal complet d'un run Projets.

Le tampon Console (`GET /api/swarm/status`) ne garde que les 200 dernières
lignes en mémoire, et les cartes agent n'en montrent que 8. Ici, **toutes**
les lignes (récit swarm + agents TinyFish) sont conservées sans plafond :

  - fichier ``backend/data/runs/<run_id>.journal.jsonl`` (artefact disque) ;
  - collection Mongo ``project_run_journal`` (sauvegardes quotidiennes VPS) ;
  - rétrocompat : les lignes ``kind=log`` sont aussi ajoutées à
    ``<run_id>.swarm.jsonl`` (déjà produit par les runs en cours).

L'API ``GET /api/projects/runs/{run_id}/journal`` relit ce journal. La carte
live ``projects`` n'est jamais écrite.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.core.events import RUNS_DIR

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")

JOURNAL_KIND_LOG = "log"
JOURNAL_KIND_AGENT = "agent"
JOURNAL_KINDS = frozenset({JOURNAL_KIND_LOG, JOURNAL_KIND_AGENT})

JOURNAL_LIMIT_DEFAULT = 2000
JOURNAL_LIMIT_MAX = 10_000
JOURNAL_DOWNLOAD_MAX = 100_000

# Lignes agent conservées sur la carte live (le fichier n'est pas tronqué).
AGENT_LIVE_TAIL = 8


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_run_id(run_id: str) -> str:
    rid = (run_id or "").strip()
    if not _RUN_ID_RE.match(rid):
        raise ValueError("invalid run_id")
    return rid


def journal_path(run_id: str) -> Path:
    return RUNS_DIR / f"{safe_run_id(run_id)}.journal.jsonl"


def swarm_log_path(run_id: str) -> Path:
    return RUNS_DIR / f"{safe_run_id(run_id)}.swarm.jsonl"


def _jsonl_paths(run_id: str) -> list[Path]:
    """Fichier unifié d'abord, sinon l'ancien .swarm.jsonl (runs déjà lancés)."""
    rid = safe_run_id(run_id)
    primary = RUNS_DIR / f"{rid}.journal.jsonl"
    legacy = RUNS_DIR / f"{rid}.swarm.jsonl"
    if primary.is_file():
        return [primary]
    if legacy.is_file():
        return [legacy]
    return []


def _public_entry(entry: dict) -> dict:
    out = {}
    for key in ("seq", "ts", "kind", "level", "msg", "agent", "engine",
                "source", "url", "status"):
        val = entry.get(key)
        if val is not None and val != "":
            out[key] = val
    if "kind" not in out:
        out["kind"] = JOURNAL_KIND_LOG
    if "level" not in out:
        out["level"] = "info"
    return out


def append_journal(run_id: str, entry: dict, seq: int | None = None) -> dict:
    """Ajoute une ligne au journal disque. Ne touche pas ``projects``."""
    rid = safe_run_id(run_id)
    rec = _public_entry(entry)
    rec["run_id"] = rid
    if seq is not None:
        rec["seq"] = int(seq)
    if not rec.get("ts"):
        rec["ts"] = now_iso()
    line = json.dumps(rec, ensure_ascii=False, default=str)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    primary = journal_path(rid)
    with _LOCK:
        with primary.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        if rec.get("kind") == JOURNAL_KIND_LOG:
            # Même récit que les runs déjà en cours (fichier .swarm.jsonl).
            with swarm_log_path(rid).open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    return rec


def iter_journal_file(run_id: str, kind: str | None = None):
    """Lit le fichier journal (ou le .swarm.jsonl de repli)."""
    want = (kind or "").strip().lower() or None
    if want == "all":
        want = None
    for path in _jsonl_paths(run_id):
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    pub = _public_entry(entry)
                    if want and pub.get("kind") != want:
                        continue
                    yield pub
        except OSError as exc:
            logger.warning("journal read failed run_id=%s path=%s: %s", run_id, path, exc)
        return


def count_journal_file(run_id: str, kind: str | None = None) -> int:
    return sum(1 for _ in iter_journal_file(run_id, kind=kind))


def read_journal_file(run_id: str, *, skip: int = 0, limit: int = JOURNAL_LIMIT_DEFAULT,
                      kind: str | None = None, tail: bool = False) -> dict:
    """Page le fichier journal. ``tail=true`` = les *limit* dernières lignes."""
    items = list(iter_journal_file(run_id, kind=kind))
    total = len(items)
    skip = max(0, int(skip or 0))
    limit = max(1, min(JOURNAL_LIMIT_MAX, int(limit or JOURNAL_LIMIT_DEFAULT)))
    if tail:
        skip = max(0, total - limit)
    page = items[skip:skip + limit]
    return {
        "run_id": run_id,
        "total": total,
        "skip": skip,
        "count": len(page),
        "kind": kind or "all",
        "items": page,
        "wrote_projects": False,
        "source": "file" if _jsonl_paths(run_id) else "empty",
    }


def journal_to_text(run_id: str, items: list[dict] | None = None) -> str:
    """Récit lisible pour téléchargement / analyse ultérieure."""
    if items is None:
        items = list(iter_journal_file(run_id))
    lines = [
        f"# Journal run Projets {run_id}",
        f"# wrote_projects: false",
        f"# lignes: {len(items)}",
        "",
    ]
    for e in items:
        ts = str(e.get("ts") or "")
        clock = ts[11:19] if len(ts) >= 19 else ts
        level = str(e.get("level") or "info").upper()
        kind = e.get("kind") or JOURNAL_KIND_LOG
        prefix = ""
        if kind == JOURNAL_KIND_AGENT:
            aid = e.get("agent") or ""
            engine = e.get("engine") or ""
            prefix = f"[{aid} {engine}] ".replace("  ", " ")
        lines.append(f"{clock} {level:<7} {prefix}{e.get('msg') or ''}".rstrip())
    return "\n".join(lines) + ("\n" if lines else "")


def journal_to_jsonl(items: list[dict]) -> str:
    return "".join(
        json.dumps(e, ensure_ascii=False, default=str) + "\n" for e in items
    )


async def mongo_insert_journal(db, rec: dict) -> None:
    if db is None or not rec:
        return
    doc = dict(rec)
    doc.setdefault("_id", f"{rec.get('run_id')}:{rec.get('seq')}")
    try:
        await db.project_run_journal.insert_one(doc)
    except Exception as exc:
        logger.warning(
            "journal Mongo insert failed run_id=%s seq=%s: %s",
            rec.get("run_id"), rec.get("seq"), exc,
        )


async def read_journal_mongo(db, run_id: str, *, skip: int = 0,
                              limit: int = JOURNAL_LIMIT_DEFAULT,
                              kind: str | None = None, tail: bool = False) -> dict:
    """Repli si le fichier a disparu : collection ``project_run_journal``."""
    rid = safe_run_id(run_id)
    q: dict = {"run_id": rid}
    want = (kind or "").strip().lower() or None
    if want and want != "all":
        q["kind"] = want
    total = await db.project_run_journal.count_documents(q)
    skip = max(0, int(skip or 0))
    limit = max(1, min(JOURNAL_LIMIT_MAX, int(limit or JOURNAL_LIMIT_DEFAULT)))
    if tail:
        skip = max(0, total - limit)
    cur = db.project_run_journal.find(q)
    if hasattr(cur, "sort"):
        cur = cur.sort("seq", 1)
    if hasattr(cur, "skip"):
        cur = cur.skip(skip)
    docs = await cur.to_list(limit)
    items = [_public_entry(d) for d in docs]
    return {
        "run_id": rid,
        "total": total,
        "skip": skip,
        "count": len(items),
        "kind": kind or "all",
        "items": items,
        "wrote_projects": False,
        "source": "mongo",
    }


async def load_journal(db, run_id: str, *, skip: int = 0,
                       limit: int = JOURNAL_LIMIT_DEFAULT,
                       kind: str | None = None, tail: bool = False) -> dict:
    """Fichier d'abord, Mongo ensuite. N'écrit jamais ``projects``."""
    if _jsonl_paths(run_id):
        return read_journal_file(
            run_id, skip=skip, limit=limit, kind=kind, tail=tail)
    if db is not None:
        try:
            out = await read_journal_mongo(
                db, run_id, skip=skip, limit=limit, kind=kind, tail=tail)
            if out["total"]:
                return out
        except Exception as exc:
            logger.warning("journal mongo fallback failed run_id=%s: %s", run_id, exc)
    return {
        "run_id": run_id,
        "total": 0,
        "skip": 0,
        "count": 0,
        "kind": kind or "all",
        "items": [],
        "wrote_projects": False,
        "source": "empty",
    }
