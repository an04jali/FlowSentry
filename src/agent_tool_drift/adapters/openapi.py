from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..models import ToolContract
from ..schema import build_object_schema, normalize_json_schema
from .base import AdapterContext, ToolAdapter, read_document_or_none, relative_path, string_or_none, walk_matching_files


class OpenAPIAdapter(ToolAdapter):
    name = "openapi"

    def scan(self, context: AdapterContext) -> list[ToolContract]:
        contracts: list[ToolContract] = []
        for path in walk_matching_files(
            context.root,
            suffixes={".json", ".yaml", ".yml"},
            include=context.config.openapi.include,
            exclude=context.config.openapi.exclude,
        ):
            data = read_document_or_none(path)
            if not isinstance(data, Mapping):
                continue
            contracts.extend(_openapi_contracts(context.root, path, data))
        return contracts


def scan_openapi_tools(root: Path, include: tuple[str, ...], exclude: tuple[str, ...]) -> list[ToolContract]:
    from ..config import AgentToolDriftConfig, FilePatternConfig

    config = AgentToolDriftConfig(openapi=FilePatternConfig(include=include, exclude=exclude))
    return OpenAPIAdapter().scan(AdapterContext(root=root, config=config))


def _openapi_contracts(root: Path, path: Path, spec: Mapping[str, Any]) -> list[ToolContract]:
    contracts: list[ToolContract] = []
    resolver = OpenAPIRefResolver(spec)
    paths = spec.get("paths")
    if not isinstance(paths, Mapping):
        return contracts

    for route, route_item in paths.items():
        route_item = resolver.resolve(route_item)
        if not isinstance(route_item, Mapping):
            continue
        for method, operation in route_item.items():
            method_name = str(method).lower()
            if method_name not in {"get", "put", "post", "delete", "patch", "head", "options"}:
                continue
            operation = resolver.resolve(operation)
            if not isinstance(operation, Mapping):
                continue
            name = operation.get("operationId") or _operation_name(method_name, str(route))
            input_schema = _openapi_input_schema(route_item, operation, resolver)
            output_schema = _openapi_output_schema(operation, resolver)
            info = spec.get("info")
            contracts.append(
                ToolContract(
                    name=str(name),
                    kind="openapi",
                    source_path=relative_path(root, path),
                    source_line=None,
                    version=string_or_none(info.get("version")) if isinstance(info, Mapping) else None,
                    description=str(operation.get("description") or operation.get("summary") or ""),
                    input_schema=normalize_json_schema(input_schema),
                    output_schema=normalize_json_schema(output_schema),
                    metadata={"adapter": OpenAPIAdapter.name, "method": method_name.upper(), "path": str(route)},
                )
            )
    return contracts


class OpenAPIRefResolver:
    def __init__(self, spec: Mapping[str, Any]) -> None:
        self.spec = spec

    def resolve(self, value: Any, seen: tuple[str, ...] = ()) -> Any:
        if isinstance(value, Mapping):
            ref = value.get("$ref")
            if isinstance(ref, str):
                target = self._resolve_ref(ref, seen)
                siblings = {key: item for key, item in value.items() if key != "$ref"}
                if isinstance(target, Mapping) and siblings:
                    merged = dict(target)
                    merged.update(siblings)
                    return self.resolve(merged, seen + (ref,))
                return self.resolve(target, seen + (ref,))
            return {key: self.resolve(item, seen) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item, seen) for item in value]
        return value

    def resolve_schema(self, schema: Any) -> Dict[str, Any]:
        resolved = self.resolve(schema)
        return dict(resolved) if isinstance(resolved, Mapping) else {}

    def _resolve_ref(self, ref: str, seen: tuple[str, ...]) -> Any:
        if ref in seen:
            return {"metadata": {"circular_ref": ref}}
        if not ref.startswith("#/"):
            return {"metadata": {"unresolved_ref": ref}}
        current: Any = self.spec
        for raw_part in ref[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, Mapping) and part in current:
                current = current[part]
            else:
                return {"metadata": {"unresolved_ref": ref}}
        return current


def _openapi_input_schema(route_item: Mapping[str, Any], operation: Mapping[str, Any], resolver: OpenAPIRefResolver) -> Dict[str, Any]:
    properties: Dict[str, Dict[str, Any]] = {}
    required: list[str] = []
    parameters_by_key: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for source in (route_item.get("parameters"), operation.get("parameters")):
        if isinstance(source, list):
            for item in source:
                if not isinstance(item, Mapping):
                    continue
                parameter = resolver.resolve(item)
                if not isinstance(parameter, Mapping):
                    continue
                key = _parameter_key(parameter)
                if key is not None:
                    parameters_by_key[key] = parameter

    name_counts: Dict[str, int] = {}
    for _location, name in parameters_by_key:
        name_counts[name] = name_counts.get(name, 0) + 1

    for (_location, name), parameter in parameters_by_key.items():
        schema = resolver.resolve_schema(parameter.get("schema"))
        property_name = _parameter_property_name(_location, name, name_counts)
        properties[property_name] = schema
        properties[property_name].setdefault("metadata", {})["in"] = parameter.get("in")
        properties[property_name].setdefault("metadata", {})["name"] = name
        if parameter.get("required"):
            required.append(property_name)

    request_body = resolver.resolve(operation.get("requestBody"))
    if isinstance(request_body, Mapping):
        body_schema = _content_schema(request_body, resolver)
        if body_schema:
            body_name = "request_body" if "body" in properties else "body"
            properties[body_name] = body_schema
            if request_body.get("required"):
                required.append(body_name)

    return build_object_schema(properties, required)


def _parameter_key(parameter: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    name = parameter.get("name")
    if not isinstance(name, str):
        return None
    location = parameter.get("in")
    return (str(location or "query"), name)


def _parameter_property_name(location: str, name: str, name_counts: Mapping[str, int]) -> str:
    if name_counts.get(name, 0) <= 1:
        return name
    return f"{_safe_identifier_part(location)}_{name}"


def _safe_identifier_part(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_") or "param"


def _openapi_output_schema(operation: Mapping[str, Any], resolver: OpenAPIRefResolver) -> Dict[str, Any]:
    responses = operation.get("responses")
    if not isinstance(responses, Mapping):
        return {}
    for status in _response_status_candidates(responses):
        response = resolver.resolve(responses.get(status))
        if isinstance(response, Mapping):
            schema = _content_schema(response, resolver)
            if schema:
                return schema
    return {}


def _response_status_candidates(responses: Mapping[Any, Any]) -> List[Any]:
    keys = list(responses)
    candidates: List[Any] = []
    for preferred in ("200", "201", "202"):
        key = _response_key(keys, preferred)
        if key is not None:
            candidates.append(key)
    candidates.extend(
        status
        for status in sorted(keys, key=lambda value: str(value))
        if status not in candidates and str(status).lower() != "default" and _is_success_response_status(str(status))
    )
    default_key = _response_key(keys, "default")
    if default_key is not None:
        candidates.append(default_key)
    return candidates


def _response_key(keys: List[Any], wanted: str) -> Optional[Any]:
    for key in keys:
        if str(key).lower() == wanted.lower():
            return key
    return None


def _is_success_response_status(status: str) -> bool:
    normalized = status.strip().upper()
    return normalized.startswith("2") and (normalized[1:].isdigit() or normalized[1:] == "XX")


def _content_schema(container: Mapping[str, Any], resolver: OpenAPIRefResolver) -> Dict[str, Any]:
    content = container.get("content")
    if not isinstance(content, Mapping):
        return {}
    for _media_type, media in _content_media_candidates(content):
        if isinstance(media, Mapping) and isinstance(media.get("schema"), Mapping):
            return resolver.resolve_schema(media["schema"])
    return {}


def _content_media_candidates(content: Mapping[str, Any]) -> List[Tuple[str, Any]]:
    items = [(str(media_type), media) for media_type, media in content.items()]
    return sorted(items, key=lambda item: _media_type_rank(item[0]))


def _media_type_rank(media_type: str) -> int:
    media = media_type.split(";", 1)[0].strip().lower()
    if media == "application/json":
        return 0
    if media.endswith("+json") or media.endswith("/json"):
        return 1
    return 2


def _operation_name(method: str, route: str) -> str:
    cleaned = route.strip("/").replace("{", "").replace("}", "")
    parts = [part for part in cleaned.replace("-", "_").split("/") if part]
    return "_".join([method.lower()] + parts) if parts else method.lower()
