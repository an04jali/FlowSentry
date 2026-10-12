from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

import yaml

from ..config import AgentToolDriftConfig
from ..models import ToolContract


@dataclass(frozen=True)
class AdapterContext:
    root: Path
    config: AgentToolDriftConfig


class ToolAdapter:
    name = "base"

    def scan(self, context: AdapterContext) -> list[ToolContract]:
        raise NotImplementedError


def walk_matching_files(
    root: Path,
    suffixes: Iterable[str],
    include: Sequence[str],
    exclude: Sequence[str],
) -> Iterator[Path]:
    suffix_set = set(suffixes)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in suffix_set:
            continue
        if not matches_any(path, root, include):
            continue
        if matches_any(path, root, exclude):
            continue
        yield path


def matches_any(path: Path, root: Path, patterns: Sequence[str]) -> bool:
    if not patterns:
        return False
    rel = relative_path(root, path)
    name = path.name
    return any(
        fnmatch.fnmatch(rel, pattern)
        or fnmatch.fnmatch(name, pattern)
        or path.match(pattern)
        for pattern in patterns
    )


def read_document_or_none(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            if path.suffix in {".yaml", ".yml"}:
                return yaml.safe_load(handle)
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError):
        return None


def relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
