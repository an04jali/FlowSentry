from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from .advice import resolve_advice
from .models import Snapshot, ToolContract


SEVERITY_ORDER = {"BREAKING": 0, "WARNING": 1, "INFO": 2}
CHANGE_PENALTIES = {
    "tool.removed": 35,
    "input.required_added": 20,
    "input.removed": 20,
    "input.rename_candidate": 4,
    "schema.type_changed": 20,
    "schema.type_narrowed": 20,
    "schema.type_widened": 1,
    "schema.property_removed": 15,
    "schema.property_rename_candidate": 4,
    "schema.required_added": 15,
    "schema.enum_narrowed": 15,
    "schema.enum_widened": 1,
    "schema.nullability_removed": 15,
    "schema.constraint_narrowed": 12,
    "schema.additional_properties_restricted": 12,
    "schema.composition_narrowed": 12,
    "schema.items_changed": 12,
    "schema.enum_changed": 10,
    "schema.default_removed": 6,
    "schema.default_changed": 6,
    "schema.constraint_changed": 6,
    "schema.composition_changed": 6,
    "tool.kind_changed": 10,
    "tool.description_changed": 5,
    "schema.property_added": 4,
    "schema.required_removed": 4,
    "schema.additional_properties_changed": 4,
    "environment.package_version_changed": 3,
    "tool.version_changed": 2,
    "tool.source_path_changed": 1,
    "tool.added": 1,
    "input.optional_added": 1,
    "input.required_removed": 0,
    "schema.default_added": 1,
    "schema.nullability_added": 1,
    "schema.constraint_relaxed": 1,
    "schema.additional_properties_relaxed": 1,
    "schema.composition_widened": 1,
}
SEVERITY_PENALTIES = {"BREAKING": 12, "WARNING": 5, "INFO": 1}
COMPATIBILITY_PENALTY_MULTIPLIERS = {
    "breaking": 1.0,
    "uncertain": 0.6,
    "unknown": 0.6,
    "backward_compatible": 0.1,
}
_ORDERED_CONSTRAINTS = {
    "minimum": "min",
    "exclusiveMinimum": "min",
    "minLength": "min",
    "minItems": "min",
    "minProperties": "min",
    "maximum": "max",
    "exclusiveMaximum": "max",
    "maxLength": "max",
    "maxItems": "max",
    "maxProperties": "max",
}
_UNORDERED_CONSTRAINTS = (
    "multipleOf",
    "pattern",
    "format",
    "uniqueItems",
    "const",
)


@dataclass(frozen=True)
class ContractChange:
    severity: str
    code: str
    tool: str
    message: str
    before: Any = None
    after: Any = None
    source_path: Optional[str] = None
    source_line: Optional[int] = None
    advice: str = ""
    advice_kind: str = "heuristic"
    advice_category: str = "unknown"
    agent_guidance: str = ""
    confidence: float = 1.0
    evidence: str = ""
    domain: str = "unknown"
    operation: str = "changed"
    direction: str = "bidirectional"
    compatibility: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "tool": self.tool,
            "message": self.message,
            "before": self.before,
            "after": self.after,
            "source_path": self.source_path,
            "source_line": self.source_line,
            "advice": self.advice,
            "advice_kind": self.advice_kind,
            "advice_category": self.advice_category,
            "agent_guidance": self.agent_guidance,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "domain": self.domain,
            "operation": self.operation,
            "direction": self.direction,
            "compatibility": self.compatibility,
        }


@dataclass(frozen=True)
class DiffResult:
    before_root: str
    after_root: str
    changes: List[ContractChange]

    @property
    def breaking_count(self) -> int:
        return sum(1 for change in self.changes if change.severity == "BREAKING")

    @property
    def warning_count(self) -> int:
        return sum(1 for change in self.changes if change.severity == "WARNING")

    @property
    def info_count(self) -> int:
        return sum(1 for change in self.changes if change.severity == "INFO")

    @property
    def has_breaking(self) -> bool:
        return self.breaking_count > 0

    @property
    def compatibility_score(self) -> int:
        penalty = sum(_change_penalty(change) for change in self.changes)
        return max(0, 100 - penalty)

    @property
    def risk_level(self) -> str:
        score = self.compatibility_score
        if score < 50 or self.breaking_count >= 5:
            return "critical"
        if score < 75 or self.has_breaking:
            return "high"
        if score < 90 or self.warning_count:
            return "medium"
        return "low"

    def sorted_changes(self) -> List[ContractChange]:
        return sorted(self.changes, key=lambda item: (SEVERITY_ORDER.get(item.severity, 99), item.tool, item.code))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "before_root": self.before_root,
            "after_root": self.after_root,
            "summary": {
                "breaking": self.breaking_count,
                "warnings": self.warning_count,
                "info": self.info_count,
                "total": len(self.changes),
                "compatibility_score": self.compatibility_score,
                "risk_level": self.risk_level,
            },
            "changes": [change.to_dict() for change in self.sorted_changes()],
        }


def compare_snapshots(before: Snapshot, after: Snapshot) -> DiffResult:
    changes: List[ContractChange] = []
    before_tools, after_tools = _diff_tool_maps(before, after)
    before_names = set(before_tools)
    after_names = set(after_tools)

    for key in sorted(before_names - after_names):
        tool = before_tools[key]
        changes.append(
            _change(
                "BREAKING",
                "tool.removed",
                tool.name,
                f"Tool '{tool.name}' was removed.",
                tool.to_dict(),
                None,
                tool.source_path,
                tool.source_line,
            )
        )

    for key in sorted(after_names - before_names):
        tool = after_tools[key]
        changes.append(
            _change(
                "INFO",
                "tool.added",
                tool.name,
                f"Tool '{tool.name}' was added.",
                None,
                tool.to_dict(),
                tool.source_path,
                tool.source_line,
            )
        )

    for key in sorted(before_names & after_names):
        changes.extend(_compare_tool(before_tools[key], after_tools[key]))

    changes.extend(_compare_environment(before.environment, after.environment))
    return DiffResult(before_root=before.root, after_root=after.root, changes=changes)


def _diff_tool_maps(before: Snapshot, after: Snapshot) -> tuple[Dict[str, ToolContract], Dict[str, ToolContract]]:
    duplicate_names = _duplicate_tool_names(before.tools) | _duplicate_tool_names(after.tools)
    if not duplicate_names:
        return before.by_name(), after.by_name()
    return _tools_by_diff_key(before.tools, duplicate_names), _tools_by_diff_key(after.tools, duplicate_names)


def _duplicate_tool_names(tools: Sequence[ToolContract]) -> Set[str]:
    seen: Set[str] = set()
    duplicates: Set[str] = set()
    for tool in tools:
        if tool.name in seen:
            duplicates.add(tool.name)
        seen.add(tool.name)
    return duplicates


def _tools_by_diff_key(tools: Sequence[ToolContract], duplicate_names: Set[str]) -> Dict[str, ToolContract]:
    result: Dict[str, ToolContract] = {}
    for tool in sorted(tools, key=lambda item: (item.name, item.kind, item.source_path, item.source_line or 0)):
        key = _tool_identity_key(tool) if tool.name in duplicate_names else tool.name
        if key in result:
            key = f"{key}:{len(result)}"
        result[key] = tool
    return result


def _tool_identity_key(tool: ToolContract) -> str:
    return f"{tool.name}#{tool.kind}:{tool.source_path}:{tool.source_line or 0}:{_tool_metadata_identity(tool)}"


def _tool_metadata_identity(tool: ToolContract) -> str:
    identity: Dict[str, Any] = {}
    for key in ("method", "path", "manifest_index", "function_name", "tool_index", "server"):
        if key in tool.metadata:
            identity[key] = tool.metadata[key]
    return _json_key(identity)


def apply_advice_config(result: DiffResult, advice_config: Any) -> DiffResult:
    overrides = getattr(advice_config, "overrides", {}) or {}
    agent_guidance = getattr(advice_config, "agent_guidance", None)
    changes = []
    for change in result.changes:
        rule = resolve_advice(change.code, overrides.get(change.code), agent_guidance=agent_guidance)
        changes.append(
            replace(
                change,
                advice=rule.suggestion,
                advice_kind=rule.kind,
                advice_category=rule.category,
                agent_guidance=rule.agent_guidance,
            )
        )
    return DiffResult(before_root=result.before_root, after_root=result.after_root, changes=changes)


def _compare_tool(before: ToolContract, after: ToolContract) -> List[ContractChange]:
    changes: List[ContractChange] = []
    tool = before.name
    source_path = after.source_path or before.source_path
    source_line = after.source_line or before.source_line

    if before.kind != after.kind:
        changes.append(_change("WARNING", "tool.kind_changed", tool, "Tool source kind changed.", before.kind, after.kind, source_path, source_line))
    if before.source_path != after.source_path:
        changes.append(_change("INFO", "tool.source_path_changed", tool, "Tool source path changed.", before.source_path, after.source_path, source_path, source_line))
    if before.version != after.version:
        changes.append(_change("INFO", "tool.version_changed", tool, "Tool version changed.", before.version, after.version, source_path, source_line))
    if _clean_description(before.description) != _clean_description(after.description):
        changes.append(_change("WARNING", "tool.description_changed", tool, "Tool description changed.", before.description, after.description, source_path, source_line))

    changes.extend(_with_location(_compare_input_schema(tool, before.input_schema, after.input_schema), source_path, source_line))
    changes.extend(_with_location(_compare_output_schema(tool, before.output_schema, after.output_schema), source_path, source_line))
    return changes


def _compare_input_schema(tool: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> List[ContractChange]:
    changes: List[ContractChange] = []
    before_props = _properties(before)
    after_props = _properties(after)
    before_required = _required(before)
    after_required = _required(after)
    rename_matches = _infer_renames(set(before_props) - set(after_props), set(after_props) - set(before_props), before_props, after_props)
    changes.extend(_compare_schema_surface(tool, "input", before, after, input_position=True))
    if (_schema_type_set(before) - {"null"}) == (_schema_type_set(after) - {"null"}):
        changes.extend(_compare_array_items(tool, "input", before, after, input_position=True))

    for name in sorted(after_required - before_required):
        if name in before_props:
            changes.append(
                _change(
                    "BREAKING",
                    "input.required_added",
                    tool,
                    f"Input '{name}' became required.",
                    False,
                    True,
                )
            )

    for name in sorted(before_required - after_required):
        if name in after_props:
            changes.append(
                _change(
                    "INFO",
                    "input.required_removed",
                    tool,
                    f"Input '{name}' is no longer required.",
                    True,
                    False,
                )
            )

    for match in rename_matches:
        changes.append(
            _change(
                "WARNING",
                "input.rename_candidate",
                tool,
                f"Input '{match.before_name}' may have been renamed to '{match.after_name}'.",
                {"name": match.before_name, "schema": before_props[match.before_name]},
                {"name": match.after_name, "schema": after_props[match.after_name]},
                confidence=match.confidence,
                evidence=match.evidence,
            )
        )

    for name in sorted(set(before_props) - set(after_props)):
        changes.append(
            _change(
                "BREAKING",
                "input.removed",
                tool,
                f"Input '{name}' was removed.",
                before_props[name],
                None,
            )
        )

    for name in sorted(set(after_props) - set(before_props)):
        severity = "BREAKING" if name in after_required else "INFO"
        code = "input.required_added" if name in after_required else "input.optional_added"
        message = f"Required input '{name}' was added." if name in after_required else f"Optional input '{name}' was added."
        changes.append(_change(severity, code, tool, message, None, after_props[name]))

    for name in sorted(set(before_props) & set(after_props)):
        changes.extend(_compare_schema_node(tool, f"input.{name}", before_props[name], after_props[name], input_position=True))

    return changes


def _compare_output_schema(tool: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> List[ContractChange]:
    return _compare_schema_node(tool, "output", before, after, input_position=False)


def _compare_schema_surface(
    tool: str,
    pointer: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    input_position: bool,
) -> List[ContractChange]:
    changes: List[ContractChange] = []
    before_types = _schema_type_set(before)
    after_types = _schema_type_set(after)
    before_non_null_types = before_types - {"null"}
    after_non_null_types = after_types - {"null"}
    if before_non_null_types != after_non_null_types:
        classification = _type_change(before_non_null_types, after_non_null_types)
        code = f"schema.type_{classification}" if classification in {"narrowed", "widened"} else "schema.type_changed"
        if input_position:
            severity = "INFO" if classification == "widened" else "BREAKING"
        else:
            severity = "WARNING" if classification in {"narrowed", "widened"} else "BREAKING"
        verb = {
            "narrowed": "types were narrowed",
            "widened": "types were widened",
            "changed": "type changed",
        }[classification]
        changes.append(
            _change(
                severity,
                code,
                tool,
                f"{pointer} {verb}.",
                sorted(before_non_null_types) if before_non_null_types else before.get("type"),
                sorted(after_non_null_types) if after_non_null_types else after.get("type"),
            )
        )

    before_nullable = _is_nullable(before)
    after_nullable = _is_nullable(after)
    if before_nullable != after_nullable:
        if before_nullable and not after_nullable:
            severity = "BREAKING" if input_position else "WARNING"
            changes.append(_change(severity, "schema.nullability_removed", tool, f"{pointer} no longer accepts null.", True, False))
        else:
            severity = "INFO" if input_position else "WARNING"
            changes.append(_change(severity, "schema.nullability_added", tool, f"{pointer} now accepts null.", False, True))

    changes.extend(_compare_default(tool, pointer, before, after, input_position))
    changes.extend(_compare_constraints(tool, pointer, before, after, input_position))
    changes.extend(_compare_additional_properties(tool, pointer, before, after, input_position))
    changes.extend(_compare_composition(tool, pointer, before, after, input_position))
    changes.extend(_compare_enum(tool, pointer, before, after, input_position))
    return changes


def _type_change(before_types: Set[str], after_types: Set[str]) -> str:
    if before_types and after_types:
        if after_types < before_types:
            return "narrowed"
        if before_types < after_types:
            return "widened"
    return "changed"


def _compare_schema_node(
    tool: str,
    pointer: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    input_position: bool,
) -> List[ContractChange]:
    changes: List[ContractChange] = []
    changes.extend(_compare_schema_surface(tool, pointer, before, after, input_position))
    before_types = _schema_type_set(before)
    after_types = _schema_type_set(after)
    before_non_null_types = before_types - {"null"}
    after_non_null_types = after_types - {"null"}

    before_props = _properties(before)
    after_props = _properties(after)
    before_required = _required(before)
    after_required = _required(after)
    rename_matches = _infer_renames(set(before_props) - set(after_props), set(after_props) - set(before_props), before_props, after_props)
    for prop in sorted(after_required - before_required):
        if prop in after_props:
            severity = "BREAKING" if input_position else "INFO"
            changes.append(_change(severity, "schema.required_added", tool, f"{pointer}.{prop} became required.", False, True))
    for prop in sorted(before_required - after_required):
        if prop in before_props:
            severity = "INFO" if input_position else "WARNING"
            changes.append(_change(severity, "schema.required_removed", tool, f"{pointer}.{prop} is no longer required.", True, False))

    for match in rename_matches:
        changes.append(
            _change(
                "WARNING",
                "schema.property_rename_candidate",
                tool,
                f"{pointer}.{match.before_name} may have been renamed to {pointer}.{match.after_name}.",
                {"name": match.before_name, "schema": before_props[match.before_name]},
                {"name": match.after_name, "schema": after_props[match.after_name]},
                confidence=match.confidence,
                evidence=match.evidence,
            )
        )

    for prop in sorted(set(before_props) - set(after_props)):
        severity = "BREAKING" if not input_position else "BREAKING"
        changes.append(_change(severity, "schema.property_removed", tool, f"{pointer}.{prop} property was removed.", before_props[prop], None))
    for prop in sorted(set(after_props) - set(before_props)):
        severity = "INFO" if input_position else "WARNING"
        changes.append(_change(severity, "schema.property_added", tool, f"{pointer}.{prop} property was added.", None, after_props[prop]))
    for prop in sorted(set(before_props) & set(after_props)):
        changes.extend(_compare_schema_node(tool, f"{pointer}.{prop}", before_props[prop], after_props[prop], input_position))

    if before_non_null_types == after_non_null_types:
        changes.extend(_compare_array_items(tool, pointer, before, after, input_position))
    return changes


def _compare_array_items(
    tool: str,
    pointer: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    input_position: bool,
) -> List[ContractChange]:
    changes: List[ContractChange] = []
    before_items = before.get("items")
    after_items = after.get("items")
    if isinstance(before_items, Mapping) and isinstance(after_items, Mapping):
        changes.extend(_compare_schema_node(tool, f"{pointer}.items", before_items, after_items, input_position))
    elif before_items is not None or after_items is not None:
        if not _json_equal(before_items, after_items):
            severity = "BREAKING" if input_position else "WARNING"
            changes.append(_change(severity, "schema.items_changed", tool, f"{pointer} array items schema changed.", before_items, after_items))
    return changes


def _compare_default(
    tool: str,
    pointer: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    input_position: bool,
) -> List[ContractChange]:
    before_has_default = "default" in before
    after_has_default = "default" in after
    if not before_has_default and not after_has_default:
        return []
    if before_has_default and not after_has_default:
        severity = "WARNING" if input_position else "INFO"
        return [_change(severity, "schema.default_removed", tool, f"{pointer} default was removed.", before.get("default"), None)]
    if after_has_default and not before_has_default:
        return [_change("INFO", "schema.default_added", tool, f"{pointer} default was added.", None, after.get("default"))]
    if not _json_equal(before.get("default"), after.get("default")):
        severity = "WARNING" if input_position else "INFO"
        return [_change(severity, "schema.default_changed", tool, f"{pointer} default changed.", before.get("default"), after.get("default"))]
    return []


def _compare_constraints(
    tool: str,
    pointer: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    input_position: bool,
) -> List[ContractChange]:
    changes: List[ContractChange] = []
    for key, direction in _ORDERED_CONSTRAINTS.items():
        if key not in before and key not in after:
            continue
        before_value = before.get(key)
        after_value = after.get(key)
        classification = _constraint_change(key, direction, before_value, after_value)
        if classification == "same":
            continue
        if classification == "narrowed":
            severity = "BREAKING" if input_position else "WARNING"
            code = "schema.constraint_narrowed"
            message = f"{pointer} constraint '{key}' was narrowed."
        elif classification == "relaxed":
            severity = "INFO" if input_position else "WARNING"
            code = "schema.constraint_relaxed"
            message = f"{pointer} constraint '{key}' was relaxed."
        else:
            severity = "WARNING"
            code = "schema.constraint_changed"
            message = f"{pointer} constraint '{key}' changed."
        changes.append(_change(severity, code, tool, message, before_value, after_value))

    for key in _UNORDERED_CONSTRAINTS:
        if key not in before and key not in after:
            continue
        before_value = before.get(key)
        after_value = after.get(key)
        before_effective = before.get(key, False) if key == "uniqueItems" else before_value
        after_effective = after.get(key, False) if key == "uniqueItems" else after_value
        if _json_equal(before_effective, after_effective):
            continue
        if key not in before:
            severity = "BREAKING" if input_position else "WARNING"
            code = "schema.constraint_narrowed"
            message = f"{pointer} constraint '{key}' was added."
        elif key not in after:
            severity = "INFO" if input_position else "WARNING"
            code = "schema.constraint_relaxed"
            message = f"{pointer} constraint '{key}' was removed."
        elif key == "uniqueItems" and isinstance(before_value, bool) and isinstance(after_value, bool):
            if after_value and not before_value:
                severity = "BREAKING" if input_position else "WARNING"
                code = "schema.constraint_narrowed"
                message = f"{pointer} constraint '{key}' was narrowed."
            else:
                severity = "INFO" if input_position else "WARNING"
                code = "schema.constraint_relaxed"
                message = f"{pointer} constraint '{key}' was relaxed."
        else:
            severity = "WARNING"
            code = "schema.constraint_changed"
            message = f"{pointer} constraint '{key}' changed."
        changes.append(_change(severity, code, tool, message, before_value, after_value))
    return changes


def _compare_enum(
    tool: str,
    pointer: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    input_position: bool,
) -> List[ContractChange]:
    before_has_enum = _has_enum(before)
    after_has_enum = _has_enum(after)
    if not before_has_enum and not after_has_enum:
        return []
    before_enum = _enum_values(before)
    after_enum = _enum_values(after)
    before_keys = set(before_enum)
    after_keys = set(after_enum)
    if before_has_enum and after_has_enum and before_keys == after_keys:
        return []

    if after_keys and before_keys and after_keys < before_keys:
        severity = "BREAKING" if input_position else "WARNING"
        return [_change(severity, "schema.enum_narrowed", tool, f"{pointer} enum values were narrowed.", _enum_report(before_enum), _enum_report(after_enum))]
    if before_keys and after_keys and before_keys < after_keys:
        severity = "INFO" if input_position else "WARNING"
        return [_change(severity, "schema.enum_widened", tool, f"{pointer} enum values were widened.", _enum_report(before_enum), _enum_report(after_enum))]
    if before_has_enum and not after_has_enum:
        severity = "INFO" if input_position else "WARNING"
        return [_change(severity, "schema.enum_widened", tool, f"{pointer} enum restriction was removed.", _enum_report(before_enum), None)]
    if after_has_enum and not before_has_enum:
        severity = "BREAKING" if input_position else "INFO"
        return [_change(severity, "schema.enum_narrowed", tool, f"{pointer} enum restriction was added.", None, _enum_report(after_enum))]

    severity = "BREAKING" if input_position else "WARNING"
    return [_change(severity, "schema.enum_changed", tool, f"{pointer} enum values changed.", _enum_report(before_enum), _enum_report(after_enum))]


def _has_enum(schema: Mapping[str, Any]) -> bool:
    raw = schema.get("enum")
    return isinstance(raw, Sequence) and not isinstance(raw, (str, bytes))


def _enum_values(schema: Mapping[str, Any]) -> Dict[str, Any]:
    raw = schema.get("enum")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return {}
    return {_json_key(value): value for value in raw}


def _enum_report(values: Mapping[str, Any]) -> List[Any]:
    return [values[key] for key in sorted(values)]


def _constraint_change(key: str, direction: str, before_value: Any, after_value: Any) -> str:
    if _json_equal(before_value, after_value):
        return "same"
    if before_value is None:
        return "narrowed"
    if after_value is None:
        return "relaxed"
    if not isinstance(before_value, (int, float)) or not isinstance(after_value, (int, float)):
        return "changed"
    if direction == "min":
        return "narrowed" if after_value > before_value else "relaxed"
    if direction == "max":
        return "narrowed" if after_value < before_value else "relaxed"
    return "changed"


def _compare_additional_properties(
    tool: str,
    pointer: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    input_position: bool,
) -> List[ContractChange]:
    if "additionalProperties" not in before and "additionalProperties" not in after:
        return []
    before_value = before.get("additionalProperties", True)
    after_value = after.get("additionalProperties", True)
    if _additional_properties_equal(before_value, after_value):
        return []
    before_unrestricted = _is_unrestricted_additional_properties(before_value)
    after_unrestricted = _is_unrestricted_additional_properties(after_value)
    before_schema = _is_restrictive_additional_properties_schema(before_value)
    after_schema = _is_restrictive_additional_properties_schema(after_value)
    if before_schema and after_schema:
        return _compare_schema_node(tool, f"{pointer}.additionalProperties", before_value, after_value, input_position)
    if (before_unrestricted and (after_schema or after_value is False)) or (before_schema and after_value is False):
        severity = "BREAKING" if input_position else "WARNING"
        return [
            _change(
                severity,
                "schema.additional_properties_restricted",
                tool,
                f"{pointer} additional properties were restricted.",
                before_value,
                after_value,
            )
        ]
    if (before_value is False and (after_unrestricted or after_schema)) or (before_schema and after_unrestricted):
        severity = "INFO" if input_position else "WARNING"
        return [
            _change(
                severity,
                "schema.additional_properties_relaxed",
                tool,
                f"{pointer} additional properties were relaxed.",
                before_value,
                after_value,
            )
        ]
    severity = "BREAKING" if input_position else "WARNING"
    return [
        _change(
            severity,
            "schema.additional_properties_changed",
            tool,
            f"{pointer} additional properties schema changed.",
            before_value,
            after_value,
        )
    ]


def _compare_composition(
    tool: str,
    pointer: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    input_position: bool,
) -> List[ContractChange]:
    changes: List[ContractChange] = []
    for key in ("oneOf", "anyOf", "allOf"):
        before_items = _schema_list(before.get(key))
        after_items = _schema_list(after.get(key))
        if _is_type_only_schema(before) and _is_type_only_schema(after):
            continue
        if not before_items and not after_items:
            continue
        if _schema_lists_equal_unordered(before_items, after_items):
            continue
        classification = _composition_change(key, len(before_items), len(after_items))
        if classification == "narrowed":
            severity = "BREAKING" if input_position else "WARNING"
            code = "schema.composition_narrowed"
            noun = "constraints" if key == "allOf" else "options"
            message = f"{pointer} {key} {noun} were narrowed."
        elif classification == "widened":
            severity = "INFO" if input_position else "WARNING"
            code = "schema.composition_widened"
            noun = "constraints" if key == "allOf" else "options"
            message = f"{pointer} {key} {noun} were widened."
        else:
            severity = "BREAKING" if input_position else "WARNING"
            code = "schema.composition_changed"
            message = f"{pointer} {key} changed."
        changes.append(_change(severity, code, tool, message, before_items or None, after_items or None))
    return changes


def _composition_change(key: str, before_count: int, after_count: int) -> str:
    if before_count == after_count:
        return "changed"
    if before_count == 0 and after_count > 0:
        return "narrowed"
    if before_count > 0 and after_count == 0:
        return "widened"
    if key == "allOf":
        return "narrowed" if after_count > before_count else "widened"
    return "widened" if after_count > before_count else "narrowed"


def _compare_environment(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[ContractChange]:
    changes: List[ContractChange] = []
    before_packages = before.get("packages") if isinstance(before.get("packages"), Mapping) else {}
    after_packages = after.get("packages") if isinstance(after.get("packages"), Mapping) else {}
    for name in sorted(set(before_packages) | set(after_packages)):
        if before_packages.get(name) != after_packages.get(name):
            changes.append(
                _change(
                    "INFO",
                    "environment.package_version_changed",
                    f"package:{name}",
                    f"Package '{name}' version changed.",
                    before_packages.get(name),
                    after_packages.get(name),
                )
            )
    return changes


def _properties(schema: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    return {str(key): value for key, value in properties.items() if isinstance(value, Mapping)}


def _required(schema: Mapping[str, Any]) -> Set[str]:
    required = schema.get("required")
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
        return set()
    return {str(item) for item in required}


def _schema_type_set(schema: Mapping[str, Any]) -> Set[str]:
    raw = schema.get("type")
    result: Set[str] = set()
    if isinstance(raw, str):
        result.add(raw)
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        result.update(str(item) for item in raw)
    if schema.get("nullable") is True:
        result.add("null")
    for key in ("oneOf", "anyOf"):
        for item in _schema_list(schema.get(key)):
            result.update(_schema_type_set(item))
    return result


def _is_nullable(schema: Mapping[str, Any]) -> bool:
    if "null" in _schema_type_set(schema):
        return True
    for key in ("oneOf", "anyOf"):
        for item in _schema_list(schema.get(key)):
            if "null" in _schema_type_set(item):
                return True
    return False


def _schema_list(value: Any) -> List[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _schema_lists_equal_unordered(left: Sequence[Mapping[str, Any]], right: Sequence[Mapping[str, Any]]) -> bool:
    return sorted(_json_key(item) for item in left) == sorted(_json_key(item) for item in right)


def _is_truthy_schema(value: Any) -> bool:
    return value is True or isinstance(value, Mapping)


def _additional_properties_equal(left: Any, right: Any) -> bool:
    return _json_equal(left, right) or (
        _is_unrestricted_additional_properties(left) and _is_unrestricted_additional_properties(right)
    )


def _is_unrestricted_additional_properties(value: Any) -> bool:
    return value is True or (isinstance(value, Mapping) and not value)


def _is_restrictive_additional_properties_schema(value: Any) -> bool:
    return isinstance(value, Mapping) and bool(value)


def _json_equal(left: Any, right: Any) -> bool:
    return _json_key(left) == _json_key(right)


def _json_key(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        return repr(value)


def _type_only_equivalent(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if not _is_type_only_schema(left) or not _is_type_only_schema(right):
        return False
    return _schema_type_set(left) == _schema_type_set(right)


def _is_type_only_schema(schema: Mapping[str, Any]) -> bool:
    allowed = {"type", "nullable", "oneOf", "anyOf", "metadata"}
    if any(key not in allowed for key in schema):
        return False
    for key in ("oneOf", "anyOf"):
        for item in _schema_list(schema.get(key)):
            if not _is_type_only_schema(item):
                return False
    return True


def _change(
    severity: str,
    code: str,
    tool: str,
    message: str,
    before: Any,
    after: Any,
    source_path: Optional[str] = None,
    source_line: Optional[int] = None,
    advice: Optional[str] = None,
    confidence: float = 1.0,
    evidence: Optional[str] = None,
    domain: Optional[str] = None,
    operation: Optional[str] = None,
    direction: Optional[str] = None,
    compatibility: Optional[str] = None,
) -> ContractChange:
    rule = resolve_advice(code)
    inferred_domain, inferred_operation, inferred_direction, inferred_compatibility = _change_semantics(code, message)
    return ContractChange(
        severity=severity,
        code=code,
        tool=tool,
        message=message,
        before=before,
        after=after,
        source_path=source_path,
        source_line=source_line,
        advice=advice or rule.suggestion,
        advice_kind=rule.kind,
        advice_category=rule.category,
        agent_guidance=rule.agent_guidance,
        confidence=round(float(confidence), 3),
        evidence=evidence or _default_evidence(code, before, after),
        domain=domain or inferred_domain,
        operation=operation or inferred_operation,
        direction=direction or inferred_direction,
        compatibility=compatibility or inferred_compatibility,
    )


def _with_location(changes: List[ContractChange], source_path: Optional[str], source_line: Optional[int]) -> List[ContractChange]:
    return [
        ContractChange(
            severity=change.severity,
            code=change.code,
            tool=change.tool,
            message=change.message,
            before=change.before,
            after=change.after,
            source_path=change.source_path or source_path,
            source_line=change.source_line or source_line,
            advice=change.advice,
            advice_kind=change.advice_kind,
            advice_category=change.advice_category,
            agent_guidance=change.agent_guidance,
            confidence=change.confidence,
            evidence=change.evidence,
            domain=change.domain,
            operation=change.operation,
            direction=change.direction,
            compatibility=change.compatibility,
        )
        for change in changes
    ]


def _clean_description(value: Optional[str]) -> str:
    return " ".join((value or "").split())


def _change_penalty(change: ContractChange) -> int:
    base = CHANGE_PENALTIES.get(change.code, SEVERITY_PENALTIES.get(change.severity, 1))
    compatibility_multiplier = COMPATIBILITY_PENALTY_MULTIPLIERS.get(change.compatibility, 0.6)
    return math.ceil(base * compatibility_multiplier * max(0.0, min(1.0, change.confidence)))


def _change_semantics(code: str, message: str) -> tuple[str, str, str, str]:
    domain = code.split(".", 1)[0] if "." in code else "unknown"
    if domain == "schema":
        direction = _direction_from_message(message)
    elif domain == "input":
        direction = "input"
    elif domain == "tool":
        direction = "tool"
    elif domain == "environment":
        direction = "environment"
    else:
        direction = "bidirectional"

    if code.endswith("_candidate"):
        return domain, "rename_candidate", direction, "uncertain"
    if code.endswith(".removed") or code.endswith("_removed"):
        operation = "removed"
    elif code.endswith(".added") or code.endswith("_added"):
        operation = "added"
    elif code.endswith("_changed"):
        operation = "changed"
    elif code.endswith("_narrowed") or code.endswith("_restricted"):
        operation = "narrowed"
    elif code.endswith("_relaxed") or code.endswith("_widened"):
        operation = "widened"
    else:
        operation = "changed"

    compatibility = _compatibility_for(code, direction, operation)
    return domain, operation, direction, compatibility


def _direction_from_message(message: str) -> str:
    if message.startswith("input"):
        return "input"
    if message.startswith("output"):
        return "output"
    return "bidirectional"


def _compatibility_for(code: str, direction: str, operation: str) -> str:
    if code in {"tool.removed", "input.required_added", "input.removed", "schema.type_changed", "schema.property_removed"}:
        return "breaking"
    if code in {"schema.default_added", "schema.default_removed", "schema.default_changed"}:
        return "uncertain"
    if operation == "rename_candidate":
        return "uncertain"
    if code == "tool.added":
        return "backward_compatible"
    if code.startswith("tool.") or code.startswith("environment."):
        return "uncertain"
    if direction == "input":
        if code == "schema.type_narrowed":
            return "breaking"
        if code == "schema.type_widened":
            return "backward_compatible"
        if code in {"schema.additional_properties_changed", "schema.composition_changed", "schema.constraint_changed", "schema.enum_changed", "schema.items_changed"}:
            return "breaking"
        if code in {"schema.nullability_removed", "schema.constraint_narrowed", "schema.additional_properties_restricted", "schema.composition_narrowed", "schema.enum_narrowed", "schema.required_added"}:
            return "breaking"
        if code in {"schema.nullability_added", "schema.constraint_relaxed", "schema.additional_properties_relaxed", "schema.composition_widened", "schema.enum_widened", "schema.required_removed", "input.optional_added", "input.required_removed"}:
            return "backward_compatible"
        if operation in {"removed", "narrowed"}:
            return "breaking"
        if operation in {"added", "widened"}:
            return "backward_compatible"
    if direction == "output":
        if code == "schema.type_narrowed":
            return "backward_compatible"
        if code == "schema.type_widened":
            return "uncertain"
        if code in {"schema.additional_properties_changed", "schema.composition_changed", "schema.constraint_changed", "schema.enum_changed", "schema.items_changed"}:
            return "uncertain"
        if code in {"schema.nullability_removed", "schema.constraint_narrowed", "schema.composition_narrowed", "schema.enum_narrowed", "schema.required_added"}:
            return "backward_compatible"
        if code in {"schema.nullability_added", "schema.constraint_relaxed", "schema.composition_widened", "schema.enum_widened", "schema.required_removed", "schema.property_added", "schema.additional_properties_restricted", "schema.additional_properties_relaxed"}:
            return "uncertain"
        if operation == "removed":
            return "breaking"
        if operation in {"added", "widened", "changed", "narrowed"}:
            return "uncertain"
    return "uncertain"


@dataclass(frozen=True)
class _RenameMatch:
    before_name: str
    after_name: str
    confidence: float
    evidence: str


def _infer_renames(
    removed: Set[str],
    added: Set[str],
    before_props: Mapping[str, Mapping[str, Any]],
    after_props: Mapping[str, Mapping[str, Any]],
) -> List[_RenameMatch]:
    candidates: list[tuple[float, str, str, str]] = []
    for before_name in removed:
        for after_name in added:
            name_score = _name_similarity(before_name, after_name)
            schema_score = _schema_similarity(before_props[before_name], after_props[after_name])
            if schema_score < 0.65:
                continue
            score = (0.7 * name_score) + (0.3 * schema_score)
            if score < 0.78:
                continue
            evidence = f"name similarity {name_score:.2f}; schema similarity {schema_score:.2f}"
            candidates.append((score, before_name, after_name, evidence))

    matches: list[_RenameMatch] = []
    used_before: set[str] = set()
    used_after: set[str] = set()
    for score, before_name, after_name, evidence in sorted(candidates, reverse=True):
        if before_name in used_before or after_name in used_after:
            continue
        used_before.add(before_name)
        used_after.add(after_name)
        matches.append(_RenameMatch(before_name=before_name, after_name=after_name, confidence=score, evidence=evidence))
    return matches


def _name_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_name(left)
    normalized_right = _normalize_name(right)
    if normalized_left == normalized_right:
        return 1.0
    ratio = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    left_tokens = set(_name_tokens(left))
    right_tokens = set(_name_tokens(right))
    token_score = 0.0
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    containment_score = 0.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        containment_score = 0.82
    return max(ratio, token_score, containment_score)


def _schema_similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    if _json_equal(left, right):
        return 1.0
    left_types = _schema_type_set(left) - {"null"}
    right_types = _schema_type_set(right) - {"null"}
    if left_types and right_types and left_types == right_types:
        return 0.78
    if left_types & right_types:
        return 0.45
    return 0.0


def _normalize_name(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _name_tokens(value: str) -> List[str]:
    chunks: list[str] = []
    current = ""
    for ch in value:
        if ch in {"_", "-", " "}:
            if current:
                chunks.append(current.lower())
                current = ""
            continue
        if ch.isupper() and current:
            chunks.append(current.lower())
            current = ch
        else:
            current += ch
    if current:
        chunks.append(current.lower())
    return chunks


def _default_evidence(code: str, before: Any, after: Any) -> str:
    if code.endswith("_changed"):
        return "before and after values differ"
    if before is None:
        return "value was added"
    if after is None:
        return "value was removed"
    return "detected by deterministic diff rule"
