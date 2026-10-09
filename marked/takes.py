"""Takes live as plain files under takes/<id>/. No database."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from marked import config


def takes_dir() -> Path:
    config.TAKES_DIR.mkdir(parents=True, exist_ok=True)
    return config.TAKES_DIR


def new_take_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


TAKE_ID_RE = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")


def take_path(take_id: str) -> Path:
    # Whitelist the generated format: a blacklist misses Windows drive-relative ids like "C:" or "D:x".
    if not take_id or not TAKE_ID_RE.fullmatch(take_id):
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
            "mode": data.get("mode", "script"),
            "topic": data.get("topic"),
        })
    return out


def improv_history(take_id: str, n: int = 5, before: str | None = None) -> list[dict]:
    """Headline numbers of up to n Improvise takes recorded before this one, oldest first."""
    before = before or (load_take(take_id) or {}).get("created_at") or "~"
    rows: list[dict] = []
    for t in list_takes():
        if t.get("mode") != "improv" or t["take_id"] == take_id or (t.get("created_at") or "") > before:
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
