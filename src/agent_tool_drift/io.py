from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .models import Snapshot


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_snapshot(path: Path) -> Snapshot:
    return Snapshot.from_dict(read_json(path))


def save_snapshot(path: Path, snapshot: Snapshot) -> None:
    write_json(path, snapshot.to_dict())
