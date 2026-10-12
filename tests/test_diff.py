from pathlib import Path
from typing import Optional

from agent_tool_drift.cli import _apply_policy, _policy_has_failure
from agent_tool_drift.config import default_config, parse_config
from agent_tool_drift.diff import apply_advice_config, compare_snapshots
from agent_tool_drift.models import Snapshot, ToolContract
from agent_tool_drift.scanner import scan_project


def test_compare_snapshots_detects_breaking_and_warning_changes() -> None:
    before = scan_project(Path("examples/python_agent"))
    after = scan_project(Path("examples/updated_python_agent"))

    result = compare_snapshots(before, after)
    codes = {change.code for change in result.changes}

    assert result.has_breaking
    assert "input.required_added" in codes
    assert "input.removed" in codes
    assert "schema.type_changed" in codes
    assert "tool.description_changed" in codes
    required_added = next(change for change in result.changes if change.code == "input.required_added")
    assert "Prefer making the new input optional" in required_added.advice
    serialized = result.to_dict()["changes"][0]
    assert serialized["advice"]
    assert serialized["advice_kind"] == "heuristic"
    assert serialized["agent_guidance"]
    assert serialized["confidence"] == 1.0
    assert serialized["evidence"]
    assert serialized["domain"]
    assert serialized["operation"]
    assert serialized["direction"]
    assert serialized["compatibility"]
    assert result.compatibility_score < 100
    assert result.risk_level in {"high", "critical"}
    assert result.to_dict()["summary"]["compatibility_score"] == result.compatibility_score
    assert result.to_dict()["summary"]["risk_level"] == result.risk_level


def test_no_changes_for_same_snapshot() -> None:
    snapshot = scan_project(Path("examples/python_agent"))

    result = compare_snapshots(snapshot, snapshot)

    assert result.changes == []
    assert result.compatibility_score == 100
    assert result.risk_level == "low"


def test_apply_advice_config_can_override_builtin_suggestions() -> None:
    before = scan_project(Path("examples/python_agent"))
    after = scan_project(Path("examples/updated_python_agent"))
    config = parse_config(
        {
            "advice": {
                "agent_guidance": "Look at project-specific agents before changing code.",
                "overrides": {
                    "input.required_added": {
                        "suggestion": "Project rule: introduce the new argument as optional first.",
                        "kind": "project",
                    }
                },
            }
        }
    )

    result = apply_advice_config(compare_snapshots(before, after), config.advice)
    required_added = next(change for change in result.changes if change.code == "input.required_added")

    assert required_added.advice == "Project rule: introduce the new argument as optional first."
    assert required_added.advice_kind == "project"
    assert required_added.agent_guidance == "Look at project-specific agents before changing code."


def test_deep_schema_diff_detects_constraint_and_shape_changes() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "query": {
                    "type": ["string", "null"],
                    "minLength": 1,
                    "maxLength": 100,
                    "default": "status",
                },
                "tags": {"type": "array", "items": {"type": "string"}},
                "payload": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["mode"],
                },
                "selector": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "integer"},
                    ]
                },
            },
            "required": ["query"],
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 3,
                    "maxLength": 120,
                    "pattern": "^[a-z]+$",
                    "default": "open",
                },
                "tags": {"type": "array", "items": {"type": "integer"}},
                "payload": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["mode", "limit"],
                },
                "selector": {"anyOf": [{"type": "string"}]},
            },
            "required": ["query"],
        }
    )

    result = compare_snapshots(before, after)
    codes = {change.code for change in result.changes}

    assert "schema.nullability_removed" in codes
    assert "schema.default_changed" in codes
    assert "schema.constraint_narrowed" in codes
    assert "schema.constraint_relaxed" in codes
    assert "schema.additional_properties_restricted" in codes
    assert "schema.required_added" in codes
    assert "schema.type_narrowed" in codes
    assert any(change.code == "schema.type_changed" and "input.tags.items" in change.message for change in result.changes)
    assert result.has_breaking


def test_diff_infers_input_and_schema_property_renames() -> None:
    before = Snapshot(
        root="memory",
        tools=[
            ToolContract(
                name="lookup",
                kind="test",
                source_path="tools.py",
                source_line=1,
                input_schema={
                    "type": "object",
                    "properties": {
                        "customer_id": {"type": "string"},
                    },
                    "required": ["customer_id"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                    },
                    "required": ["name"],
                },
            )
        ],
    )
    after = Snapshot(
        root="memory",
        tools=[
            ToolContract(
                name="lookup",
                kind="test",
                source_path="tools.py",
                source_line=1,
                input_schema={
                    "type": "object",
                    "properties": {
                        "customerId": {"type": "string"},
                    },
                    "required": ["customerId"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "display_name": {"type": "string"},
                    },
                    "required": ["display_name"],
                },
            )
        ],
    )

    result = compare_snapshots(before, after)
    codes = {change.code for change in result.changes}
    input_rename = next(change for change in result.changes if change.code == "input.rename_candidate")
    output_rename = next(change for change in result.changes if change.code == "schema.property_rename_candidate")

    assert "input.removed" in codes
    assert "input.required_added" in codes
    assert "schema.property_removed" in codes
    assert "schema.property_added" in codes
    assert input_rename.confidence >= 0.9
    assert "name similarity" in input_rename.evidence
    assert input_rename.compatibility == "uncertain"
    assert input_rename.operation == "rename_candidate"
    assert input_rename.direction == "input"
    assert output_rename.confidence < 1.0
    assert output_rename.before["name"] == "name"
    assert output_rename.after["name"] == "display_name"
    assert output_rename.compatibility == "uncertain"


def test_semantically_equivalent_nullable_schemas_do_not_drift() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "query": {"type": ["string", "null"]},
            },
            "required": ["query"],
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "query": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "null"},
                    ]
                },
            },
            "required": ["query"],
        }
    )

    result = compare_snapshots(before, after)

    assert result.changes == []


def test_composition_schema_reordering_does_not_drift() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "integer"},
                    ]
                }
            },
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "value": {
                    "anyOf": [
                        {"type": "integer"},
                        {"type": "string"},
                    ]
                }
            },
        }
    )

    result = compare_snapshots(before, after)

    assert result.changes == []


def test_root_input_schema_type_changes_are_detected() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
        }
    )
    after = _snapshot_with_schema({"type": "array", "items": {"type": "string"}})

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.type_changed")

    assert change.message == "input type changed."
    assert change.severity == "BREAKING"
    assert change.compatibility == "breaking"


def test_input_type_widening_is_not_policy_breaking() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"query": {"type": ["integer", "string"]}},
        }
    )

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.type_widened")

    assert change.message == "input.query types were widened."
    assert change.severity == "INFO"
    assert change.compatibility == "backward_compatible"
    assert not _policy_has_failure(result, default_config())


def test_output_type_narrowing_is_not_policy_breaking() -> None:
    before = _snapshot_with_schema({}, output_schema={"type": ["integer", "string"]})
    after = _snapshot_with_schema({}, output_schema={"type": "string"})

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.type_narrowed")

    assert change.message == "output types were narrowed."
    assert change.severity == "WARNING"
    assert change.compatibility == "backward_compatible"
    assert not _policy_has_failure(result, default_config())


def test_additional_properties_semantics_handle_boolean_and_empty_schema() -> None:
    unrestricted_true = _snapshot_with_schema({"type": "object", "additionalProperties": True})
    unrestricted_empty_schema = _snapshot_with_schema({"type": "object", "additionalProperties": {}})
    restricted_schema = _snapshot_with_schema({"type": "object", "additionalProperties": {"type": "string"}})

    assert compare_snapshots(unrestricted_true, unrestricted_empty_schema).changes == []

    restricted = compare_snapshots(unrestricted_true, restricted_schema)
    restricted_change = next(change for change in restricted.changes if change.code == "schema.additional_properties_restricted")
    assert restricted_change.severity == "BREAKING"
    assert restricted_change.compatibility == "breaking"

    relaxed = compare_snapshots(restricted_schema, unrestricted_true)
    relaxed_change = next(change for change in relaxed.changes if change.code == "schema.additional_properties_relaxed")
    assert relaxed_change.severity == "INFO"
    assert relaxed_change.compatibility == "backward_compatible"


def test_unique_items_constraint_direction_is_classified() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"tags": {"type": "array", "uniqueItems": False}},
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"tags": {"type": "array", "uniqueItems": True}},
        }
    )

    narrowed = compare_snapshots(before, after)
    narrowed_change = next(change for change in narrowed.changes if change.code == "schema.constraint_narrowed")

    assert narrowed_change.message == "input.tags constraint 'uniqueItems' was narrowed."
    assert narrowed_change.severity == "BREAKING"
    assert narrowed_change.compatibility == "breaking"

    relaxed = compare_snapshots(after, before)
    relaxed_change = next(change for change in relaxed.changes if change.code == "schema.constraint_relaxed")

    assert relaxed_change.message == "input.tags constraint 'uniqueItems' was relaxed."
    assert relaxed_change.severity == "INFO"
    assert relaxed_change.compatibility == "backward_compatible"


def test_unique_items_false_and_missing_are_equivalent() -> None:
    missing = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"tags": {"type": "array"}},
        }
    )
    explicit_false = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"tags": {"type": "array", "uniqueItems": False}},
        }
    )

    assert compare_snapshots(missing, explicit_false).changes == []
    assert compare_snapshots(explicit_false, missing).changes == []


def test_output_enum_narrowing_is_not_treated_as_breaking_policy_failure() -> None:
    before = _snapshot_with_schema({}, output_schema={"type": "string", "enum": ["error", "ok"]})
    after = _snapshot_with_schema({}, output_schema={"type": "string", "enum": ["ok"]})

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.enum_narrowed")

    assert change.direction == "output"
    assert change.severity == "WARNING"
    assert change.compatibility == "backward_compatible"
    assert not result.has_breaking
    assert not _policy_has_failure(result, default_config())
    assert _policy_has_failure(result, parse_config({"policy": {"fail_on": ["schema.enum_narrowed"]}}))
    assert result.compatibility_score >= 95


def test_default_policy_still_fails_on_breaking_input_compatibility() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["fast", "slow"]}},
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["fast"]}},
        }
    )

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.enum_narrowed")

    assert change.direction == "input"
    assert change.compatibility == "breaking"
    assert _policy_has_failure(result, default_config())
    assert _policy_has_failure(result, parse_config({"policy": {"fail_on": ["direction:input"]}}))


def test_empty_input_enum_added_is_breaking() -> None:
    before = _snapshot_with_schema({"type": "object", "properties": {"mode": {"type": "string"}}})
    after = _snapshot_with_schema({"type": "object", "properties": {"mode": {"type": "string", "enum": []}}})

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.enum_narrowed")

    assert change.direction == "input"
    assert change.after == []
    assert change.compatibility == "breaking"
    assert result.has_breaking


def test_empty_input_enum_removed_is_backward_compatible() -> None:
    before = _snapshot_with_schema({"type": "object", "properties": {"mode": {"type": "string", "enum": []}}})
    after = _snapshot_with_schema({"type": "object", "properties": {"mode": {"type": "string"}}})

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.enum_widened")

    assert change.direction == "input"
    assert change.before == []
    assert change.compatibility == "backward_compatible"
    assert not result.has_breaking


def test_empty_enum_to_empty_enum_does_not_drift() -> None:
    before = _snapshot_with_schema({"type": "object", "properties": {"mode": {"type": "string", "enum": []}}})
    after = _snapshot_with_schema({"type": "object", "properties": {"mode": {"type": "string", "enum": []}}})

    assert compare_snapshots(before, after).changes == []


def test_policy_ignore_uses_same_selectors_as_fail_on() -> None:
    before = _snapshot_with_schema({}, output_schema={"type": "object", "properties": {}})
    after = _snapshot_with_schema({}, output_schema={"type": "object", "properties": {"trace_id": {"type": "string"}}})

    result = compare_snapshots(before, after)
    filtered = _apply_policy(result, parse_config({"policy": {"ignore": ["direction:output"]}}))

    assert any(change.direction == "output" for change in result.changes)
    assert filtered.changes == []


def test_policy_selectors_are_case_insensitive() -> None:
    before = _snapshot_with_schema({"type": "object", "properties": {"query": {"type": "string"}}})
    after = _snapshot_with_schema({"type": "object", "properties": {}})

    result = compare_snapshots(before, after)

    assert _policy_has_failure(result, parse_config({"policy": {"fail_on": ["SeVeRiTy:breaking"]}}))
    assert _apply_policy(result, parse_config({"policy": {"ignore": ["DOMAIN:INPUT"]}})).changes == []


def test_input_allof_added_constraint_is_narrowing_and_policy_failure() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "payload": {
                    "allOf": [
                        {"type": "object"},
                    ]
                }
            },
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "payload": {
                    "allOf": [
                        {"type": "object"},
                        {"required": ["id"]},
                    ]
                }
            },
        }
    )

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.composition_narrowed")

    assert change.message == "input.payload allOf constraints were narrowed."
    assert change.compatibility == "breaking"
    assert _policy_has_failure(result, default_config())


def test_default_removed_is_uncertain_not_policy_breaking() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"query": {"type": "string", "default": "status"}},
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        }
    )

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.default_removed")

    assert change.severity == "WARNING"
    assert change.compatibility == "uncertain"
    assert not _policy_has_failure(result, default_config())


def test_default_changed_is_uncertain_not_policy_breaking() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 5}},
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        }
    )

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.default_changed")

    assert change.before == 5
    assert change.after == 10
    assert change.compatibility == "uncertain"
    assert not _policy_has_failure(result, default_config())


def test_output_mixed_enum_change_is_uncertain_not_breaking() -> None:
    before = _snapshot_with_schema({}, output_schema={"type": "string", "enum": ["error", "ok"]})
    after = _snapshot_with_schema({}, output_schema={"type": "string", "enum": ["ok", "pending"]})

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.enum_changed")

    assert change.direction == "output"
    assert change.severity == "WARNING"
    assert change.compatibility == "uncertain"
    assert not _policy_has_failure(result, default_config())


def test_enum_diff_handles_object_values() -> None:
    before = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "filter": {
                    "enum": [
                        {"kind": "open"},
                        {"kind": "closed"},
                    ]
                }
            },
        }
    )
    after = _snapshot_with_schema(
        {
            "type": "object",
            "properties": {
                "filter": {
                    "enum": [
                        {"kind": "open"},
                    ]
                }
            },
        }
    )

    result = compare_snapshots(before, after)
    change = next(change for change in result.changes if change.code == "schema.enum_narrowed")

    assert change.before == [{"kind": "closed"}, {"kind": "open"}]
    assert change.after == [{"kind": "open"}]
    assert change.compatibility == "breaking"


def test_duplicate_tool_names_are_matched_by_source_identity() -> None:
    before = Snapshot(
        root="memory",
        tools=[
            ToolContract(
                name="lookup",
                kind="manifest",
                source_path="agent-tools.json",
                input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            ),
            ToolContract(
                name="lookup",
                kind="openapi",
                source_path="openapi.json",
                input_schema={"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"]},
            ),
        ],
    )
    after = Snapshot(
        root="memory",
        tools=[
            ToolContract(
                name="lookup",
                kind="openapi",
                source_path="openapi.json",
                input_schema={"type": "object", "properties": {"ticket_id": {"type": "string"}}, "required": ["ticket_id"]},
            ),
        ],
    )

    result = compare_snapshots(before, after)

    assert [change.code for change in result.changes] == ["tool.removed"]
    assert result.changes[0].tool == "lookup"
    assert result.changes[0].before["kind"] == "manifest"


def test_duplicate_openapi_operation_ids_use_method_and_path_identity() -> None:
    before = Snapshot(
        root="memory",
        tools=[
            ToolContract(
                name="lookup",
                kind="openapi",
                source_path="openapi.json",
                input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                metadata={"method": "GET", "path": "/users/{id}"},
            ),
            ToolContract(
                name="lookup",
                kind="openapi",
                source_path="openapi.json",
                input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                metadata={"method": "GET", "path": "/tickets/{id}"},
            ),
        ],
    )
    after = Snapshot(
        root="memory",
        tools=[
            ToolContract(
                name="lookup",
                kind="openapi",
                source_path="openapi.json",
                input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                metadata={"method": "GET", "path": "/tickets/{id}"},
            ),
        ],
    )

    result = compare_snapshots(before, after)

    assert [change.code for change in result.changes] == ["tool.removed"]
    assert result.changes[0].before["metadata"]["path"] == "/users/{id}"


def test_snapshot_from_dict_coerces_source_line_for_stable_duplicate_matching() -> None:
    before = Snapshot.from_dict(
        {
            "root": "memory",
            "tools": [
                {
                    "name": "lookup",
                    "kind": "python",
                    "source_path": "a.py",
                    "source_line": "10",
                    "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
                {
                    "name": "lookup",
                    "kind": "python",
                    "source_path": "b.py",
                    "source_line": 20,
                    "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}},
                },
            ],
        }
    )
    after = Snapshot.from_dict(
        {
            "root": "memory",
            "tools": [
                {
                    "name": "lookup",
                    "kind": "python",
                    "source_path": "b.py",
                    "source_line": "20",
                    "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}},
                }
            ],
        }
    )

    result = compare_snapshots(before, after)

    assert before.tools[0].source_line == 10
    assert after.tools[0].source_line == 20
    assert [change.code for change in result.changes] == ["tool.removed"]
    assert result.changes[0].before["source_path"] == "a.py"


def test_snapshot_from_dict_ignores_malformed_environment() -> None:
    snapshot = Snapshot.from_dict(
        {
            "root": "memory",
            "environment": ["not", "an", "object"],
            "tools": [
                {
                    "name": "lookup",
                    "kind": "manifest",
                    "source_path": "tools.json",
                }
            ],
        }
    )

    assert snapshot.environment == {}
    assert snapshot.tools[0].name == "lookup"


def _snapshot_with_schema(input_schema: dict, output_schema: Optional[dict] = None) -> Snapshot:
    return Snapshot(
        root="memory",
        tools=[
            ToolContract(
                name="search",
                kind="test",
                source_path="tools.py",
                source_line=1,
                input_schema=input_schema,
                output_schema=output_schema or {},
            )
        ],
    )
