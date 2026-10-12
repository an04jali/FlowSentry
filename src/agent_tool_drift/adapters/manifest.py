from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

from ..models import ToolContract
from ..schema import normalize_json_schema
from .base import AdapterContext, ToolAdapter, read_document_or_none, relative_path, string_or_none, walk_matching_files


class ManifestAdapter(ToolAdapter):
    name = "manifest"

    def scan(self, context: AdapterContext) -> list[ToolContract]:
        contracts: list[ToolContract] = []
        for path in walk_matching_files(
            context.root,
            suffixes={".json", ".yaml", ".yml"},
            include=context.config.manifests.include,
            exclude=context.config.manifests.exclude,
        ):
            data = read_document_or_none(path)
            if data is None:
                continue
            for index, entry in enumerate(_manifest_entries(data)):
                contract = _manifest_contract(context.root, path, entry, index)
                if contract:
                    contracts.append(contract)
        return contracts


def scan_manifest_tools(root: Path, include: tuple[str, ...], exclude: tuple[str, ...]) -> list[ToolContract]:
    from ..config import AgentToolDriftConfig, FilePatternConfig

    config = AgentToolDriftConfig(manifests=FilePatternConfig(include=include, exclude=exclude))
    return ManifestAdapter().scan(AdapterContext(root=root, config=config))


def _manifest_entries(data: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, Mapping):
                yield item
        return
    if not isinstance(data, Mapping):
        return
    if isinstance(data.get("name"), str) or (data.get("type") == "function" and isinstance(data.get("function"), Mapping)):
        yield data
        return
    for key in ("tools", "functions"):
        items = data.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping):
                    yield item


def _manifest_contract(root: Path, path: Path, entry: Mapping[str, Any], index: int) -> Optional[ToolContract]:
    payload: Mapping[str, Any] = entry
    kind = "manifest"
    if entry.get("type") == "function" and isinstance(entry.get("function"), Mapping):
        payload = entry["function"]  # type: ignore[index]
        kind = "openai-function"

    name = payload.get("name")
    if not isinstance(name, str) or not name:
        return None

    input_schema = (
        payload.get("input_schema")
        or payload.get("inputSchema")
        or payload.get("parameters")
        or payload.get("schema")
        or {}
    )
    output_schema = payload.get("output_schema") or payload.get("outputSchema") or {}
    description = payload.get("description") or ""

    return ToolContract(
        name=name,
        kind=kind,
        source_path=relative_path(root, path),
        source_line=None,
        version=string_or_none(payload.get("version") or entry.get("version")),
        description=str(description),
        input_schema=normalize_json_schema(dict(input_schema) if isinstance(input_schema, Mapping) else {}),
        output_schema=normalize_json_schema(dict(output_schema) if isinstance(output_schema, Mapping) else {}),
        metadata={"adapter": ManifestAdapter.name, "manifest_index": index},
    )
