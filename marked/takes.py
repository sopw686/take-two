"""Takes live as plain files under takes/<id>/. No database.

take.json holds a take's own metadata: mode, kind (take / drill / example),
label, the settings it was requested with and, while it is being processed,
status, stage and error. A take is finished when analysis.json exists; the
status in take.json only matters before that, so a failed re-analysis never
hides a finished take. Folders from before take.json existed still work.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from marked import config
from marked.marks import blank_comments

META = "take.json"
# Identifies the server process that last worked on a take (recorded in take.json for diagnosis).
BOOT_ID = uuid.uuid4().hex
# Takes being processed by this process, and takes created here and waiting to be processed.
ACTIVE: set[str] = set()
QUEUED: set[str] = set()
SUFFIX_RE = re.compile(r"\.[a-z0-9]{1,5}")
TAKE_ID_RE = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")

_lock = threading.Lock()
_take_locks: dict[str, threading.RLock] = {}


class Busy(Exception):
    """The take is already being processed."""


def takes_dir() -> Path:
    config.TAKES_DIR.mkdir(parents=True, exist_ok=True)
    return config.TAKES_DIR


def new_take_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def take_path(take_id: str) -> Path:
    # Whitelist the generated format: a blacklist misses Windows drive-relative ids like "C:" or "D:x".
    if not take_id or not TAKE_ID_RE.fullmatch(take_id):
        raise ValueError("bad take id")
    return takes_dir() / take_id


def save_json(path: Path, data: dict) -> None:
    """Write via a temp file and an atomic rename, so a reader never sees half a file.

    On Windows the rename fails while another process (OneDrive, an antivirus scan,
    a reader) holds the target open, so it is retried briefly.
    """
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 7:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.05 * (attempt + 1))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def take_lock(take_id: str) -> threading.RLock:
    """Serializes read-modify-write of one take's files within this process."""
    with _lock:
        return _take_locks.setdefault(take_id, threading.RLock())


def is_busy(take_id: str) -> bool:
    return take_id in ACTIVE or take_id in QUEUED


@contextlib.contextmanager
def claim(take_id: str) -> Iterator[None]:
    """Mark a take as being processed; a second claim raises Busy."""
    with _lock:
        if take_id in ACTIVE:
            raise Busy(take_id)
        ACTIVE.add(take_id)
        QUEUED.discard(take_id)
    try:
        yield
    finally:
        with _lock:
            ACTIVE.discard(take_id)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _created_from_id(take_id: str) -> str:
    return datetime.strptime(take_id[:15], "%Y%m%d-%H%M%S").isoformat(timespec="seconds")


def orig_audio(take_id: str) -> Path | None:
    """The upload as received (audio.orig.<ext>), if it is still there."""
    return next((p for p in sorted(take_path(take_id).glob("audio.orig.*")) if p.is_file()), None)


def load_meta(take_id: str) -> dict:
    """take.json with defaults filled in; made up from the folder's files for older takes."""
    tdir = take_path(take_id)
    meta: dict = {}
    p = tdir / META
    if p.exists():
        try:
            meta = load_json(p)
        except ValueError:
            meta = {}
    base: dict = {"v": 1, "created_at": _created_from_id(take_id), "mode": None, "kind": "take", "label": "",
                  "original_name": "", "settings": None, "drill_of": None, "drill": None, "example": None,
                  "status": None, "stage": None, "error": None, "owner": None, "timing": {}}
    if not meta:
        a = tdir / "analysis.json"
        if a.exists():
            try:
                data = load_json(a)
                base.update({k: data[k] for k in ("created_at", "label", "kind", "drill_of", "drill", "example", "timing")
                             if data.get(k) is not None})
                base["mode"] = data.get("mode", "script")
            except ValueError:
                pass
        if base["mode"] is None:
            if (tdir / "improv.json").exists():
                base["mode"] = "improv"
            elif (tdir / "script.md").exists():
                base["mode"] = "script"
    return {**base, **meta}


def update_meta(take_id: str, **fields: object) -> dict:
    with take_lock(take_id):
        meta = load_meta(take_id)
        meta.update(fields)
        save_json(take_path(take_id) / META, meta)
        return meta


def update_analysis(take_id: str, fn: Callable[[dict], dict | None]) -> dict | None:
    """Apply fn to the stored analysis under the take's lock and save the result (None: no change)."""
    with take_lock(take_id):
        data = load_take(take_id)
        if data is None:
            return None
        new = fn(data)
        if new is not None:
            save_json(take_path(take_id) / "analysis.json", new)
            return new
        return data


def take_status(take_id: str) -> dict:
    """{status: done | processing | failed, stage, error, retryable}. Never writes."""
    tdir = take_path(take_id)
    if (tdir / "analysis.json").exists():
        return {"status": "done", "stage": None, "error": None, "retryable": False}
    meta = load_meta(take_id)
    status, error = meta.get("status") or "failed", meta.get("error")
    if status == "processing" and not is_busy(take_id):
        # Only this process can be working on it: a server that stopped (crash, Ctrl+C, a --reload restart)
        # comes back as a new process, and its unfinished take must be retryable right away.
        status, error = "failed", "Interrupted: the server stopped while analyzing this take."
    if status != "processing":
        status = "failed"
        error = error or "Analysis did not finish (no details were saved)."
    return {"status": status, "stage": meta.get("stage") if status == "processing" else None, "error": error,
            "retryable": status == "failed" and orig_audio(take_id) is not None}


def new_take(mode: str, *, upload: bytes | Path, original_name: str = "", settings: dict | None = None,
             label: str = "", script: str | None = None, improv: dict | None = None, kind: str = "take",
             drill_of: str | None = None, drill: dict | None = None, example: str | None = None) -> str:
    """Create a take folder holding the upload and everything needed to (re)run its analysis."""
    take_id = new_take_id()
    while (takes_dir() / take_id).exists():
        take_id = new_take_id()
    tdir = take_path(take_id)
    tdir.mkdir(parents=True)
    with _lock:
        QUEUED.add(take_id)
    try:
        suffix = Path(original_name).suffix.lower()
        if not SUFFIX_RE.fullmatch(suffix):
            # Also keeps names like "a.wav:x" (an NTFS alternate data stream) out of the folder.
            suffix = ".bin"
        save_json(tdir / META, {"v": 1, "created_at": _now(), "mode": mode, "kind": kind, "label": label,
                                "original_name": original_name, "settings": settings, "drill_of": drill_of,
                                "drill": drill, "example": example, "status": "processing", "stage": "queued",
                                "error": None, "owner": {"boot_id": BOOT_ID, "started_at": _now()}, "timing": {}})
        if script is not None:
            (tdir / "script.md").write_text(script, encoding="utf-8")
        if improv is not None:
            save_json(tdir / "improv.json", improv)
        dst = tdir / f"audio.orig{suffix}"
        if isinstance(upload, (bytes, bytearray)):
            dst.write_bytes(upload)
        else:
            shutil.copyfile(upload, dst)
    except BaseException:
        # Nothing usable was saved; do not leave a take that looks busy forever.
        with _lock:
            QUEUED.discard(take_id)
        shutil.rmtree(tdir, ignore_errors=True)
        raise
    return take_id


def delete_take(take_id: str) -> None:
    tdir = take_path(take_id)
    for attempt in range(8):
        try:
            shutil.rmtree(tdir)
            break
        except FileNotFoundError:
            break
        except PermissionError:  # a file still open elsewhere (audio playback, OneDrive); try again shortly
            if attempt == 7:
                raise
            time.sleep(0.1 * (attempt + 1))
    with _lock:
        _take_locks.pop(take_id, None)
        QUEUED.discard(take_id)


def list_takes(include_unfinished: bool = True) -> list[dict]:
    out = []
    for d in sorted(takes_dir().iterdir(), reverse=True):
        if not d.is_dir() or not TAKE_ID_RE.fullmatch(d.name):
            continue
        a = d / "analysis.json"
        if a.exists():
            try:
                data = load_json(a)
            except ValueError:
                continue
            out.append({
                "take_id": data.get("take_id", d.name),
                "created_at": data.get("created_at"),
                "duration_s": data.get("duration_s"),
                "summary": data.get("summary", []),
                "label": data.get("label", ""),
                "stt": data.get("stt", {}),
                "mode": data.get("mode", "script"),
                "topic": data.get("topic"),
                "kind": data.get("kind", "take"),
                "drill_of": data.get("drill_of"),
                "status": "done",
            })
        elif include_unfinished:
            meta = load_meta(d.name)
            topic = None
            if (d / "improv.json").exists():
                try:
                    topic = load_json(d / "improv.json").get("topic")
                except ValueError:
                    pass
            out.append({
                "take_id": d.name, "created_at": meta["created_at"], "duration_s": None, "summary": [],
                "label": meta.get("label", ""), "stt": {}, "mode": meta.get("mode") or "script", "topic": topic,
                "kind": meta.get("kind", "take"), "drill_of": meta.get("drill_of"),
                "needs_script": meta.get("mode") is None,
                **take_status(d.name),
            })
    return out


def improv_history(take_id: str, n: int = 5, before: str | None = None) -> list[dict]:
    """Headline numbers of up to n Improvise takes recorded before this one, oldest first."""
    before = before or (load_take(take_id) or {}).get("created_at") or "~"
    rows: list[dict] = []
    for t in list_takes(include_unfinished=False):
        if t.get("mode") != "improv" or t.get("kind") != "take" or t["take_id"] == take_id \
                or (t.get("created_at") or "") > before:
            continue
        r = (load_take(t["take_id"]) or {}).get("improv")
        if not r:
            continue
        rows.append({
            "take_id": t["take_id"], "created_at": t.get("created_at"), "topic": t.get("topic"),
            "goal_s": r["goal"].get("goal_s"), "delta_s": r["goal"].get("delta_s"),
            "wpm": r["pace"].get("overall_wpm"), "fillers_per_100": r["fillers"].get("per_100"),
            "hedges_per_100": r["hedges"].get("per_100"), "hesitations_per_min": r["hesitation"].get("per_min"),
            "pitch_range_st": r["engagement"].get("pitch_range_st"),
        })
        if len(rows) >= n:
            break
    return list(reversed(rows))


def load_take(take_id: str) -> dict | None:
    p = take_path(take_id) / "analysis.json"
    return load_json(p) if p.exists() else None


def latest_median_wpm() -> float | None:
    """The speaker's median from their latest real script take (not an example or a drill)."""
    for t in list_takes(include_unfinished=False):
        if t.get("mode") != "script" or t.get("kind") != "take":
            continue
        data = load_take(t["take_id"])
        wpm = (data or {}).get("baseline", {}).get("median_wpm")
        if wpm:
            return float(wpm)
    return None


def script_key(text: str) -> str:
    """Hash of the script text ignoring comments and whitespace differences, to group takes of one script."""
    import hashlib
    norm = " ".join(blank_comments(text).split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def analysis_script_key(a: dict) -> str | None:
    p = take_path(a["take_id"]) / "script.md"
    if p.exists():
        return script_key(p.read_text(encoding="utf-8"))
    return a.get("script_key")


def same_script(key: str, *, before: str | None = None, kinds: tuple[str, ...] = ("take",)) -> list[dict]:
    """Finished script takes of the given kinds whose script matches key, oldest first."""
    out = []
    for t in list_takes(include_unfinished=False):
        if t.get("mode") == "improv" or t.get("kind", "take") not in kinds:
            continue
        if before is not None and (t.get("created_at") or "") > before:
            continue
        a = load_take(t["take_id"])
        if a and analysis_script_key(a) == key:
            out.append(a)
    out.sort(key=lambda a: a.get("created_at") or "")
    return out


def takes_with_same_script(take_id: str) -> list[dict]:
    """All real takes sharing this take's script, oldest first (includes the take itself).

    An example or a drill is only ever compared with itself: a synthetic voice or a
    one-line retry says nothing about the speaker's full takes.
    """
    current = load_take(take_id)
    if not current:
        return []
    if current.get("kind", "take") != "take":
        return [current]
    key = analysis_script_key(current)
    if key is None:
        return [current]
    group = same_script(key)
    if not any(a.get("take_id") == take_id for a in group):
        group.append(current)
        group.sort(key=lambda a: a.get("created_at") or "")
    return group
