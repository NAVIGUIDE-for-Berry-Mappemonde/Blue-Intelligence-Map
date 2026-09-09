"""Runs isolés communs (Marinas, Capitaineries, AMP).

Calque Projets / PoE : un `run_id`, des collections `*_run_*`, snapshot de
règles, journal d'événements. Les collections live (`marinas`,
`capitaineries`, `amp_sites`, `anchorages`) ne sont jamais écrites.

Les documents déjà présents dans `marina_runs` (dumps live historiques) sont
conservés : `open_run` n'écrase que par `_id` inexistant (`$setOnInsert`).
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import time
import uuid

from app.core.events import RunRecorder
from app.core.run_rules import attach_rules, bind_rules, snapshot_for_run, snapshot_list_fields
from app.services.run_fingerprint import build_code_fingerprint, merge_run_params

_current_run_id: ContextVar[str | None] = ContextVar("isolated_run_id", default=None)


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    mode: str
    meta_coll: str
    items_coll: str
    events_coll: str
    wrote_flag: str
    cursor_coll: str | None = None
    extra_items_coll: str | None = None


DATASETS = {
    "marinas": DatasetSpec(
        key="marinas",
        mode="marinas",
        meta_coll="marina_runs",
        items_coll="marina_run_marinas",
        events_coll="marina_run_events",
        wrote_flag="wrote_marinas",
        cursor_coll="marina_run_cursors",
        extra_items_coll="marina_run_anchorages",
    ),
    "capitaineries": DatasetSpec(
        key="capitaineries",
        mode="capitaineries",
        meta_coll="capitainerie_runs",
        items_coll="capitainerie_run_sites",
        events_coll="capitainerie_run_events",
        wrote_flag="wrote_capitaineries",
        cursor_coll="capitainerie_run_cursors",
    ),
    "amp": DatasetSpec(
        key="amp",
        mode="amp",
        meta_coll="amp_runs",
        items_coll="amp_run_sites",
        events_coll="amp_run_events",
        wrote_flag="wrote_amp_sites",
    ),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]


def spec_for(dataset: str) -> DatasetSpec:
    if dataset not in DATASETS:
        raise ValueError(f"dataset inconnu: {dataset}")
    return DATASETS[dataset]


def current_run_id() -> str | None:
    return _current_run_id.get()


def bind_run(run_id: str | None):
    return _current_run_id.set(run_id)


def reset_run(token) -> None:
    _current_run_id.reset(token)


def cursor_id(default: str) -> str:
    return current_run_id() or default


def run_doc_id(raw_id) -> str:
    rid = current_run_id()
    sid = str(raw_id)
    return f"{rid}:{sid}" if rid else sid


def stamp(doc: dict, *, source_id=None, wrote_flag: str | None = None) -> dict:
    """Pose run_id / source_id / wrote_* sur une copie. No-op hors run isolé."""
    rid = current_run_id()
    out = dict(doc)
    if not rid:
        return out
    sid = str(source_id if source_id is not None else (
        out.get("source_id") or out.get("osm_id") or out.get("site_id")
        or out.get("dedup_key") or out.get("_id") or ""))
    out["run_id"] = rid
    if sid:
        out["source_id"] = sid
    if wrote_flag:
        out[wrote_flag] = False
    return out


def identity_query(field: str, value) -> dict:
    q = {field: value}
    rid = current_run_id()
    if rid:
        q["run_id"] = rid
    return q


def coll(db, name: str):
    return getattr(db, name)


async def ensure_indexes(db, dataset: str | None = None) -> None:
    keys = (dataset,) if dataset else tuple(DATASETS)
    for key in keys:
        spec = spec_for(key)
        try:
            await coll(db, spec.meta_coll).create_index("created_at")
            await coll(db, spec.meta_coll).create_index("state")
            await coll(db, spec.items_coll).create_index([("run_id", 1), ("source_id", 1)])
            await coll(db, spec.items_coll).create_index("run_id")
            await coll(db, spec.events_coll).create_index([("run_id", 1), ("seq", 1)])
            if spec.cursor_coll:
                await coll(db, spec.cursor_coll).create_index("run_id")
            if spec.extra_items_coll:
                await coll(db, spec.extra_items_coll).create_index(
                    [("run_id", 1), ("dedup_key", 1)])
                await coll(db, spec.extra_items_coll).create_index("run_id")
        except Exception:
            pass


async def open_run(
    db, dataset: str, *, kind: str, label: str = "",
    settings: dict | None = None, run_id: str | None = None,
    extra_params: dict | None = None, rules_overrides: dict | None = None,
    profile: str | None = None, to_file: bool = True,
    resume: bool = False,
) -> dict:
    """Crée (ou reprend) un document de run. N'écrit jamais la collection live."""
    spec = spec_for(dataset)
    await ensure_indexes(db, dataset)
    settings = settings or {}
    meta = coll(db, spec.meta_coll)

    if resume and not run_id:
        running = await meta.find_one({"state": "running", "kind": kind})
        if running:
            run_id = str(running.get("_id"))

    rid = run_id or new_run_id()
    existing = await meta.find_one({"_id": rid})
    # Dumps live historiques (`wrote_*=true`) : ne pas les reprendre ni les muter.
    if existing and existing.get(spec.wrote_flag):
        existing = None
        rid = new_run_id()
    rules = snapshot_for_run(mode=spec.mode, settings=settings,
                             overrides=rules_overrides, profile=profile)
    bind_rules(rules)
    fingerprint = build_code_fingerprint(settings)
    params = attach_rules(merge_run_params({
        "kind": kind,
        "label": label,
        spec.wrote_flag: False,
        "profile": rules["profile"],
        **(extra_params or {}),
    }, fingerprint), rules)
    rec = RunRecorder(rid, db=db, events_coll=spec.events_coll, to_file=to_file)

    if existing:
        patch = {
            "state": "running",
            "resumed": True,
            "error": None,
        }
        if not existing.get(spec.wrote_flag):
            patch[spec.wrote_flag] = False
        await meta.update_one({"_id": rid}, {"$set": patch})
        await rec.event("run_resume", dataset=dataset, kind=kind,
                        **{spec.wrote_flag: False})
    else:
        doc = {
            "_id": rid,
            "label": label or f"{dataset}-{kind}",
            "dataset": dataset,
            "kind": kind,
            "mode": spec.mode,
            "state": "running",
            spec.wrote_flag: False,
            "params": params,
            "created_at": now_iso(),
            "started_at": now_iso(),
            "error": None,
        }
        await meta.update_one({"_id": rid}, {"$setOnInsert": doc}, upsert=True)
        await rec.event("run_start", dataset=dataset, kind=kind,
                        label=doc["label"], **{spec.wrote_flag: False})

    token = bind_run(rid)
    return {
        "run_id": rid,
        "recorder": rec,
        "spec": spec,
        "token": token,
        spec.wrote_flag: False,
        "resumed": bool(existing),
    }


async def finalize_run(db, dataset: str, run_id: str, *, cancelled: bool = False,
                       error: str | None = None, extra: dict | None = None):
    if not run_id:
        return
    spec = spec_for(dataset)
    rec = RunRecorder(run_id, db=db, events_coll=spec.events_coll)
    n = 0
    try:
        n = await coll(db, spec.items_coll).count_documents({"run_id": run_id})
    except Exception:
        n = 0
    extra_n = 0
    if spec.extra_items_coll:
        try:
            extra_n = await coll(db, spec.extra_items_coll).count_documents(
                {"run_id": run_id})
        except Exception:
            extra_n = 0
    summary = {
        "run_id": run_id,
        spec.wrote_flag: False,
        "items": n,
        "extra_items": extra_n,
        "cancelled": cancelled,
        **(extra or {}),
    }
    state = "cancelled" if cancelled else ("failed" if error else "done")
    meta = coll(db, spec.meta_coll)
    existing = None
    try:
        existing = await meta.find_one({"_id": run_id})
    except Exception:
        existing = None
    wrote_live = bool(existing and existing.get(spec.wrote_flag))
    await meta.update_one({"_id": run_id}, {"$set": {
        "state": state,
        "finished_at": now_iso(),
        "error": error,
        "summary": summary,
        spec.wrote_flag: True if wrote_live else False,
    }})
    await rec.event("run_done", **summary)


async def write_item(db, dataset: str, run_id: str, doc: dict, *,
                     source_id=None) -> str:
    """Upsert une fiche dans l'espace du run. Jamais la collection live."""
    if not run_id:
        raise ValueError("run_id required — isolated run only")
    spec = spec_for(dataset)
    sid = str(source_id if source_id is not None else (
        doc.get("source_id") or doc.get("osm_id") or doc.get("site_id")
        or doc.get("dedup_key") or doc.get("_id") or ""))
    if not sid:
        raise ValueError("source_id required")
    payload = {k: v for k, v in doc.items() if k != "_id"}
    payload["run_id"] = run_id
    payload["source_id"] = sid
    payload[spec.wrote_flag] = False
    if "updated_at" not in payload:
        payload["updated_at"] = now_iso()
    items = coll(db, spec.items_coll)
    existing = await items.find_one({"run_id": run_id, "source_id": sid})
    if existing:
        await items.update_one({"_id": existing["_id"]}, {"$set": payload})
        return str(existing["_id"])
    new_id = f"{run_id}:{sid}"
    payload["_id"] = new_id
    payload["created_at"] = now_iso()
    await items.insert_one(payload)
    return new_id


async def write_extra_item(db, dataset: str, run_id: str, doc: dict, *,
                           source_id=None) -> str:
    spec = spec_for(dataset)
    if not spec.extra_items_coll:
        raise ValueError(f"{dataset} has no extra items collection")
    sid = str(source_id if source_id is not None else (
        doc.get("source_id") or doc.get("dedup_key") or doc.get("_id") or ""))
    payload = {k: v for k, v in doc.items() if k != "_id"}
    payload["run_id"] = run_id
    payload["source_id"] = sid
    payload[spec.wrote_flag] = False
    extra = coll(db, spec.extra_items_coll)
    existing = await extra.find_one({"run_id": run_id, "source_id": sid})
    if existing:
        await extra.update_one({"_id": existing["_id"]}, {"$set": payload})
        return str(existing["_id"])
    new_id = f"{run_id}:{sid}"
    payload["_id"] = new_id
    payload["created_at"] = now_iso()
    await extra.insert_one(payload)
    return new_id


async def find_item(db, dataset: str, run_id: str, entity_id: str) -> dict | None:
    spec = spec_for(dataset)
    items = coll(db, spec.items_coll)
    eid = str(entity_id)
    for q in (
        {"run_id": run_id, "source_id": eid},
        {"run_id": run_id, "osm_id": eid},
        {"run_id": run_id, "site_id": eid},
        {"run_id": run_id, "_id": eid},
        {"_id": f"{run_id}:{eid}"},
    ):
        doc = await items.find_one(q)
        if doc:
            return doc
    return None


def _summary_count(doc: dict) -> int:
    summary = doc.get("summary") or {}
    for key in ("items", "inserted", "fetched_raw", "found", "selected"):
        n = summary.get(key)
        if isinstance(n, int) and n > 0:
            return n
    inserted = summary.get("inserted") or 0
    updated = summary.get("updated") or 0
    try:
        return int(inserted) + int(updated)
    except (TypeError, ValueError):
        return 0


async def list_meta_runs(db, dataset: str, *, skip_kinds: tuple[str, ...] = ()) -> list[dict]:
    """Liste les méta-runs (y compris les dumps live historiques)."""
    spec = spec_for(dataset)
    try:
        docs = await coll(db, spec.meta_coll).find({}).to_list(200)
    except Exception:
        return []
    docs.sort(key=lambda d: d.get("created_at") or "", reverse=True)
    out = []
    for d in docs:
        kind = d.get("kind") or ""
        if skip_kinds and kind in skip_kinds:
            continue
        rid = str(d.get("_id"))
        n = 0
        try:
            n = await coll(db, spec.items_coll).count_documents({"run_id": rid})
        except Exception:
            n = 0
        if n == 0 and spec.extra_items_coll and kind == "anchorages":
            try:
                n = await coll(db, spec.extra_items_coll).count_documents(
                    {"run_id": rid})
            except Exception:
                n = 0
        if n == 0:
            n = _summary_count(d)
        wrote_live = bool(d.get(spec.wrote_flag))
        fields = snapshot_list_fields(d.get("params") or {})
        out.append({
            "id": rid,
            "label": d.get("label") or rid,
            "state": d.get("state"),
            "created_at": d.get("created_at"),
            "count": n,
            "dataset": dataset,
            "kind": kind,
            "wrote_live": wrote_live,
            spec.wrote_flag: False if not wrote_live else True,
            "recommended": False,
            "profile": fields["profile"],
            "hash": fields["hash"],
            "hash8": fields["hash8"],
            "counts": fields["counts"],
        })
    return out


async def get_meta_run(db, dataset: str, run_id: str) -> dict | None:
    """Détail d'un run : snapshot `chosen` complet."""
    spec = spec_for(dataset)
    try:
        doc = await coll(db, spec.meta_coll).find_one({"_id": run_id})
    except Exception:
        doc = None
    if not doc:
        return None
    rules = (doc.get("params") or {}).get("rules") or {}
    if not isinstance(rules, dict):
        rules = {}
    fields = snapshot_list_fields(doc.get("params") or {})
    wrote_live = bool(doc.get(spec.wrote_flag))
    return {
        "id": str(doc.get("_id")),
        "label": doc.get("label") or str(doc.get("_id")),
        "state": doc.get("state"),
        "created_at": doc.get("created_at"),
        "finished_at": doc.get("finished_at"),
        "kind": doc.get("kind") or "",
        "dataset": dataset,
        "error": doc.get("error"),
        "summary": doc.get("summary"),
        "wrote_live": wrote_live,
        spec.wrote_flag: False if not wrote_live else True,
        "profile": fields["profile"],
        "hash": fields["hash"],
        "hash8": fields["hash8"],
        "counts": fields["counts"],
        "chosen": rules.get("chosen") or {},
        "params": {"rules": rules},
    }
