"""Takes live as plain files under takes/<id>/. No database."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path

from marked import config


def takes_dir() -> Path:
    config.TAKES_DIR.mkdir(parents=True, exist_ok=True)
    return config.TAKES_DIR


def new_take_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


def take_path(take_id: str) -> Path:
    if not take_id or "/" in take_id or "\\" in take_id or ".." in take_id:
        raise ValueError("bad take id")
    return takes_dir() / take_id


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def list_takes() -> list[dict]:
    out = []
    for d in sorted(takes_dir().iterdir(), reverse=True):
        a = d / "analysis.json"
        if not d.is_dir() or not a.exists():
            continue
        try:
            data = load_json(a)
        except Exception:
            continue
        out.append({
            "take_id": data.get("take_id", d.name),
            "created_at": data.get("created_at"),
            "duration_s": data.get("duration_s"),
            "summary": data.get("summary", []),
            "label": data.get("label", ""),
            "stt": data.get("stt", {}),
        })
    return out


def load_take(take_id: str) -> dict | None:
    p = take_path(take_id) / "analysis.json"
    return load_json(p) if p.exists() else None


def latest_median_wpm() -> float | None:
    for t in list_takes():
        data = load_take(t["take_id"])
        wpm = (data or {}).get("baseline", {}).get("median_wpm")
        if wpm:
            return float(wpm)
    return None


def script_key(text: str) -> str:
    """Hash of the script text ignoring whitespace differences, to group takes of one script."""
    import hashlib
    norm = " ".join(text.split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def takes_with_same_script(take_id: str) -> list[dict]:
    """All analyses sharing this take's script, oldest first (includes the take itself)."""
    current = load_take(take_id)
    if not current:
        return []
    def key_of(a: dict) -> str | None:
        if a.get("script_key"):
            return a["script_key"]
        p = take_path(a["take_id"]) / "script.md"
        return script_key(p.read_text(encoding="utf-8")) if p.exists() else None

    key = key_of(current)
    out = []
    for t in list_takes():
        a = load_take(t["take_id"])
        if a and key is not None and key_of(a) == key:
            out.append(a)
    out.sort(key=lambda a: a.get("created_at") or "")
    return out
