"""
events_core — Journal d'événements structurés du pipeline PoE.

Chaque micro-étape du pipeline émet un événement persistant
{run_id, seq, ts, mrgid, zone, step, payload} qui consigne les DÉCISIONS et
les CANDIDATS REJETÉS (requêtes émises, URLs écartées et pourquoi, verdicts du
gatekeeper, niveaux de cascade, sorties LLM/NER, candidats de géocodage des
deux fournisseurs, arbitrages…).

Double sortie :
  - collection Mongo `poe_run_events` (requêtable — alimente le rapport de run) ;
  - fichier JSONL `backend/data/runs/<run_id>.jsonl` (lecture directe, artefact).

Ces traces servent l'audit, le diff entre runs, le rapport quantitatif et les
futurs jeux d'entraînement ML (weak supervision).
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field

from app.config import DATA_DIR

RUNS_DIR = DATA_DIR / "runs"

_MAX_STR = 4000          # troncature des chaînes longues (sorties LLM…)
_MAX_LIST = 60           # troncature des listes longues (SERP…)


def _clip(value):
    """Tronque récursivement le payload (les événements restent bornés)."""
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR else value[:_MAX_STR] + "…[tronqué]"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        clipped = [_clip(v) for v in list(value)[:_MAX_LIST]]
        if len(value) > _MAX_LIST:
            clipped.append(f"…[{len(value) - _MAX_LIST} éléments tronqués]")
        return clipped
    return value


class RunRecorder:
    """Journal d'un run : écrit chaque événement dans Mongo + JSONL."""

    def __init__(self, run_id: str, db=None, to_file: bool = True):
        self.run_id = run_id
        self.db = db
        self._seq = 0
        self._seq_lock = asyncio.Lock()
        self.path = None
        if to_file:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            self.path = RUNS_DIR / f"{run_id}.jsonl"

    async def event(self, step: str, mrgid: int | None = None,
                    zone: str | None = None, **payload):
        async with self._seq_lock:
            self._seq += 1
            seq = self._seq
        doc = {
            "_id": str(uuid.uuid4()),
            "run_id": self.run_id,
            "seq": seq,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "t": round(time.time(), 3),
            "mrgid": mrgid,
            "zone": zone,
            "step": step,
            "payload": _clip(payload),
        }
        if self.db is not None:
            try:
                await self.db.poe_run_events.insert_one(doc)
            except Exception:
                pass  # le journal ne doit jamais faire échouer le pipeline
        if self.path is not None:
            try:
                line = json.dumps({k: v for k, v in doc.items() if k != "_id"},
                                  ensure_ascii=False, default=str)
                await asyncio.to_thread(self._append_line, line)
            except Exception:
                pass

    def _append_line(self, line: str):
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class ZoneRecorder:
    """Recorder lié à une zone : mrgid/zone renseignés automatiquement."""

    def __init__(self, recorder: RunRecorder, mrgid: int, zone: str | None):
        self._rec = recorder
        self.mrgid = int(mrgid)
        self.zone = zone

    async def event(self, step: str, **payload):
        await self._rec.event(step, mrgid=self.mrgid, zone=self.zone, **payload)


async def emit(rec, step: str, **payload):
    """Émission tolérante : no-op si aucun recorder n'est branché."""
    if rec is not None:
        await rec.event(step, **payload)


@dataclass
class RunContext:
    """Contexte d'un run versionné : identifiant, journal et collections cibles.
    Quand un RunContext est passé au pipeline, l'écriture se fait dans l'espace
    du run (poe_run_ports / poe_run_zones) — les collections v1 (poe_ports,
    eez_zones) ne sont JAMAIS touchées (contrainte « trésor » du PRD)."""
    run_id: str
    recorder: RunRecorder
    ports_coll: str = "poe_run_ports"
    zones_coll: str = "poe_run_zones"
    started_at: float = field(default_factory=time.time)
