"""Job-Modell und persistenter Job-Store (JSON-Datei)."""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

ACTIVE = {"queued", "downloading", "processing"}


@dataclass
class Job:
    url: str
    series: str
    season: int
    episode: int
    title: str
    quality: str
    user: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "queued"  # queued | downloading | processing | done | error | cancelled
    progress: float = 0.0
    speed: str = ""
    eta: str = ""
    error: str = ""
    filename: str = ""
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.RLock()
        self._jobs: dict[str, Job] = {}
        self._cancel: set[str] = set()
        self._load()

    # -- Persistenz ---------------------------------------------------------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        known = set(Job.__dataclass_fields__)
        for item in raw:
            try:
                job = Job(**{k: v for k, v in item.items() if k in known})
            except TypeError:
                continue
            self._jobs[job.id] = job

    def save(self) -> None:
        with self._lock:
            data = [j.to_dict() for j in self._jobs.values()]
            tmp = self._path.with_suffix(".tmp")
            try:
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
                tmp.replace(self._path)
            except OSError:
                pass

    # -- Zugriff ------------------------------------------------------------
    def add(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self.save()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status in ACTIVE:
                return False
            del self._jobs[job_id]
            self.save()
            return True

    def clear_finished(self) -> int:
        with self._lock:
            ids = [j.id for j in self._jobs.values() if j.status not in ACTIVE]
            for job_id in ids:
                del self._jobs[job_id]
            self.save()
            return len(ids)

    def update(self, job: Job, **changes) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)

    # -- Abbruch ------------------------------------------------------------
    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in ACTIVE:
                return False
            self._cancel.add(job_id)
            if job.status == "queued":
                job.status = "cancelled"
                job.finished = time.time()
                self.save()
            return True

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._cancel
