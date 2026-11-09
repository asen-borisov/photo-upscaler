"""Background queue: one photo at a time, with progress, time left and cancel."""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image

from . import engine, pipeline

_ids = itertools.count(1)


@dataclass
class Job:
    path: str
    name: str
    in_size: tuple[int, int] | None = None
    id: int = field(default_factory=lambda: next(_ids))
    status: str = "queued"          # queued | running | done | skipped | error | cancelled
    progress: float = 0.0
    message: str = ""
    out_path: str = ""
    out_size: tuple[int, int] | None = None
    started: float = 0.0
    seconds: float = 0.0
    eta: float | None = None
    log: str = ""


class Queue:
    def __init__(self, workdir: Path):
        self.workdir = workdir
        self.jobs: list[Job] = []
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.settings: pipeline.Settings | None = None
        self.sec_per_mp: float | None = None  # measured on this machine, per output megapixel

    # ---- adding -------------------------------------------------------
    def add_paths(self, paths: list[str]) -> int:
        files: list[Path] = []
        for p in map(Path, paths):
            if p.is_dir():
                files += sorted(f for f in p.iterdir() if f.is_file() and pipeline.is_supported(f))
            elif p.is_file() and pipeline.is_supported(p):
                files.append(p)
        added = 0
        with self.lock:
            known = {j.path for j in self.jobs if j.status in ("queued", "running")}
            for f in files:
                if str(f) in known:
                    continue
                try:
                    with Image.open(f) as im:
                        size = im.size
                        if im.getexif().get(pipeline.ORIENTATION) in (5, 6, 7, 8):
                            size = size[::-1]
                except Exception:
                    size = None
                job = Job(str(f), f.name, size)
                if size is None:
                    job.status, job.message = "error", "Can't read this file"
                self.jobs.append(job)
                added += 1
        return added

    def remove(self, job_id: int) -> None:
        with self.lock:
            self.jobs = [j for j in self.jobs if not (j.id == job_id and j.status != "running")]

    def clear_finished(self) -> None:
        with self.lock:
            self.jobs = [j for j in self.jobs if j.status in ("queued", "running")]

    def get(self, job_id: int) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    # ---- running ------------------------------------------------------
    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def start(self, settings: pipeline.Settings) -> None:
        engine.get_model(settings.model)  # fail fast on a bad model
        pipeline.target_size(100, 100, settings)
        with self.lock:
            for j in self.jobs:  # allow a rerun of failed/cancelled items
                if j.status in ("cancelled", "error") and j.in_size:
                    j.status, j.message, j.progress = "queued", "", 0.0
        if self.running:
            return
        self.settings = settings
        self.cancel.clear()
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def stop(self) -> None:
        self.cancel.set()
        with self.lock:
            for j in self.jobs:
                if j.status == "queued":
                    j.status, j.message = "cancelled", "Cancelled"

    def _loop(self) -> None:
        while not self.cancel.is_set():
            with self.lock:
                job = next((j for j in self.jobs if j.status == "queued"), None)
                if job is None:
                    return
                job.status, job.started, job.progress = "running", time.time(), 0.0
            self._run(job)

    def _run(self, job: Job) -> None:
        s = self.settings

        def progress(f: float) -> None:
            job.progress = f
            el = time.time() - job.started
            job.eta = el / f * (1 - f) if f > 0.08 else self._estimate(job)

        job.eta = self._estimate(job)
        try:
            r = pipeline.process(Path(job.path), s, progress, self.cancel, self.workdir)
            job.status, job.out_path, job.out_size = "done", str(r.out_path), r.out_size
            job.message = "; ".join(r.notes)
            job.log = f"{job.name}: {r.in_size[0]}x{r.in_size[1]} -> {r.out_size[0]}x{r.out_size[1]} in {r.seconds:.0f}s"
            mp = r.in_size[0] * r.in_size[1] * 16 / 1e6  # the engine always renders 4x
            rate = r.seconds / max(mp, 0.01)
            self.sec_per_mp = rate if self.sec_per_mp is None else 0.5 * (self.sec_per_mp + rate)
        except pipeline.Skipped as e:
            job.status, job.message = "skipped", f"Skipped: {e}"
        except engine.Cancelled:
            job.status, job.message = "cancelled", "Cancelled"
        except Exception as e:  # show any failure on the item, keep the queue going
            job.status, job.message = "error", str(e)
        job.seconds = time.time() - job.started
        job.progress = 1.0 if job.status == "done" else job.progress
        job.eta = None

    def _estimate(self, job: Job) -> float | None:
        if not self.sec_per_mp or not job.in_size:
            return None
        return self.sec_per_mp * job.in_size[0] * job.in_size[1] * 16 / 1e6

    # ---- status -------------------------------------------------------
    def snapshot(self) -> dict:
        with self.lock:
            jobs = [asdict(j) for j in self.jobs]
        remaining = 0.0
        for j in self.jobs:
            if j.status == "running" and j.eta:
                remaining += j.eta
            elif j.status == "queued":
                remaining += self._estimate(j) or 0
        return {"jobs": jobs, "running": self.running, "eta_total": remaining or None}
