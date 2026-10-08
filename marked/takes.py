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
