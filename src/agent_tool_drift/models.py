from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional


SCHEMA_VERSION = "1"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ToolContract:
    name: str
    kind: str
    source_path: str
    source_line: Optional[int] = None
    version: Optional[str] = None
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "source_path": self.source_path,
            "source_line": self.source_line,
            "version": self.version,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ToolContract":
        if not isinstance(data, Mapping):
            raise ValueError("Snapshot tool entries must be objects.")
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Snapshot tool entry is missing a non-empty string 'name'.")
        return cls(
            name=name,
            kind=str(data.get("kind", "unknown")),
            source_path=str(data.get("source_path", "")),
            source_line=_optional_positive_int(data.get("source_line")),
            version=str(data["version"]) if data.get("version") is not None else None,
            description=str(data.get("description", "")),
            input_schema=_mapping_dict(data.get("input_schema")),
            output_schema=_mapping_dict(data.get("output_schema")),
            metadata=_mapping_dict(data.get("metadata")),
        )


@dataclass(frozen=True)
class Snapshot:
    root: str
    tools: List[ToolContract]
    generated_at: str = field(default_factory=utc_now_iso)
    schema_version: str = SCHEMA_VERSION
    environment: Dict[str, Any] = field(default_factory=dict)

    def sorted_tools(self) -> List[ToolContract]:
        return sorted(self.tools, key=lambda tool: (tool.name, tool.kind, tool.source_path))

    def by_name(self) -> Dict[str, ToolContract]:
        result: Dict[str, ToolContract] = {}
        for tool in self.sorted_tools():
            if tool.name not in result:
                result[tool.name] = tool
            else:
                duplicate_name = f"{tool.name}#{tool.kind}:{tool.source_path}:{tool.source_line or 0}"
                result[duplicate_name] = tool
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "root": self.root,
            "environment": self.environment,
            "tools": [tool.to_dict() for tool in self.sorted_tools()],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Snapshot":
        if not isinstance(data, Mapping):
            raise ValueError("Snapshot file must contain a JSON object.")
        raw_tools = data.get("tools", [])
        if not isinstance(raw_tools, list):
            raise ValueError("Snapshot field 'tools' must be a list.")
        tools = [ToolContract.from_dict(item) for item in raw_tools]
        return cls(
            root=str(data.get("root", "")),
            tools=tools,
            generated_at=str(data.get("generated_at", utc_now_iso())),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
            environment=_mapping_dict(data.get("environment")),
        )


def contracts_from_dicts(items: Iterable[Mapping[str, Any]]) -> List[ToolContract]:
    return [ToolContract.from_dict(item) for item in items]


def _optional_positive_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _mapping_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
