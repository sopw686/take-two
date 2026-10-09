"""Background analysis jobs, so the page can show progress stage by stage.

One worker thread: speech-to-text runs one take at a time anyway, so a second take
honestly waits as "queued" instead of pretending to run. The job id is the take id,
and the stage is also written to take.json, so a page reload (or a server restart)
can still find out what happened to the take. Polling, not WebSockets: one small
GET every half second is plenty for a local app and needs no new dependency.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from take_two import pipeline, takes

log = logging.getLogger(__name__)

KEEP_FINISHED = 50
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="marked-job")
_jobs: dict[str, dict] = {}
_finished: list[str] = []
_lock = threading.Lock()


def submit(take_id: str, mode: str, work: Callable[[pipeline.Progress], dict]) -> dict:
    """Queue work(progress) for a take that already exists on disk. Raises takes.Busy if it is queued or running."""
    with _lock:
        job = _jobs.get(take_id)
        if (job and job["status"] in ("queued", "running")) or take_id in takes.ACTIVE:
            raise takes.Busy(take_id)
        _jobs[take_id] = {"take_id": take_id, "mode": mode, "status": "queued", "stage": "queued", "error": None}
    takes.reserve(take_id)  # listings show it as being processed, not interrupted

    def progress(stage: str) -> None:
        with _lock:
            _jobs[take_id].update(status="running", stage=stage)

    def run() -> None:
        with _lock:
            _jobs[take_id].update(status="running", stage="starting")
        try:
            work(progress)
            update = {"status": "done", "stage": None}
        except takes.Busy:
            update = {"status": "failed", "error": "this take is already being analyzed"}
        except pipeline.TakeFailed as exc:
            update = {"status": "failed", "error": exc.message}
        except Exception as exc:  # anything else still ends the job visibly
            log.exception("job %s failed", take_id)
            update = {"status": "failed", "error": str(exc) or type(exc).__name__}
        finally:
            takes.release(take_id)
        with _lock:
            _jobs[take_id].update(update)
            _finished.append(take_id)
            while len(_finished) > KEEP_FINISHED:
                old = _finished.pop(0)
                if _jobs.get(old, {}).get("status") in ("done", "failed"):
                    _jobs.pop(old, None)

    _pool.submit(run)
    return status(take_id)


def status(take_id: str) -> dict:
    """{take_id, mode, status: queued | running | done | failed, stage, stages, error}."""
    with _lock:
        job = dict(_jobs[take_id]) if take_id in _jobs else None
    if job is None:
        # Not submitted in this process (or forgotten): the folder says what happened.
        meta = takes.load_meta(take_id)
        st = takes.take_status(take_id)
        job = {"take_id": take_id, "mode": meta.get("mode") or "script",
               "status": {"done": "done", "processing": "running"}.get(st["status"], "failed"),
               "stage": st.get("stage"), "error": st.get("error")}
    job["stages"] = list(pipeline.STAGES.get(job["mode"], pipeline.STAGES["script"]))
    return job
