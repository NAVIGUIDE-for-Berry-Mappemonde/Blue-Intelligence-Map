"""
app.core.tasks — État générique des tâches de fond (unifie les 4 classes
historiques : TaskState de poe_routes, EnrichBatchState et ZeeComputeState de
server.py, BuildState de marinas.py).
"""
import time


class TaskState:
    """État in-memory d'une tâche/batch de fond, avec journal borné."""

    def __init__(self, max_logs: int = 800):
        self.max_logs = max_logs
        self.running = False
        self.started_at = None
        self.finished_at = None
        self.progress = 0
        self.total = 0
        self.results: list[dict] = []
        self.logs: list[str] = []
        self.error = None
        self.summary = None
        self.result = None
        self.cancel = False
        self.run_id = None

    def log(self, msg: str):
        self.logs.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]

    def reset(self):
        self.__init__(self.max_logs)

    def start(self):
        self.reset()
        self.running = True
        self.started_at = time.time()

    def finish(self):
        self.finished_at = time.time()
        self.running = False

    def status(self):
        return {
            "running": self.running, "started_at": self.started_at, "finished_at": self.finished_at,
            "progress": self.progress, "total": self.total, "results": self.results[-40:],
            "logs_tail": self.logs[-60:], "error": self.error, "summary": self.summary,
            "cancelling": self.cancel and self.running,
            "run_id": self.run_id,
        }


# Alias sémantiques (signatures historiques)
BuildState = TaskState


def prune_tasks(registry: dict, max_age_s: int = 3600):
    """Purge les tâches à la demande (dict par id) terminées depuis > max_age_s."""
    now = time.time()
    for k in list(registry.keys()):
        t = registry.get(k) or {}
        finished = t.get("finished_at") or 0
        if finished and (now - finished) > max_age_s:
            registry.pop(k, None)


def new_task() -> dict:
    """Descripteur d'une tâche unitaire à la demande (enrich marina/projet, génération PoE)."""
    return {"state": "running", "started_at": time.time(), "finished_at": None,
            "result": None, "error": None, "logs": []}
