from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


AGENT_GUIDANCE = (
    "This is heuristic guidance, not an automatic fix. A capable migration agent "
    "should inspect the before/after contracts, source code, callers, tests, and "
    "product context, then apply, adapt, or ignore this suggestion."
)


@dataclass(frozen=True)
class AdviceRule:
    code: str
    category: str
    suggestion: str
    kind: str = "heuristic"
    agent_guidance: str = AGENT_GUIDANCE


ADVICE_RULES = {
    "tool.removed": AdviceRule(
        code="tool.removed",
        category="tool",
        suggestion="Keep a compatibility wrapper with the old tool name, or update every agent config, prompt, and workflow that can call it.",
    ),
    "tool.added": AdviceRule(
        code="tool.added",
        category="tool",
        suggestion="Review whether this tool should be exposed to the agent, then refresh the baseline if the addition is intentional.",
    ),
    "tool.kind_changed": AdviceRule(
        code="tool.kind_changed",
        category="tool",
        suggestion="Verify runtime behavior, auth, serialization, and execution semantics because the tool moved across scanner/runtime kinds.",
    ),
    "tool.source_path_changed": AdviceRule(
        code="tool.source_path_changed",
        category="tool",
        suggestion="Usually this is a source move; refresh the baseline after confirming the public name and schemas stayed stable.",
    ),
    "tool.version_changed": AdviceRule(
        code="tool.version_changed",
        category="tool",
        suggestion="Review the tool release notes and rerun integration tests before accepting the new version.",
    ),
    "tool.description_changed": AdviceRule(
        code="tool.description_changed",
        category="tool",
        suggestion="Review prompt/eval behavior because description changes can change when the model chooses this tool.",
    ),
    "input.required_added": AdviceRule(
        code="input.required_added",
        category="input",
        suggestion="Prefer making the new input optional with a default; if it is truly required, update all callers and agent instructions together.",
    ),
    "input.required_removed": AdviceRule(
        code="input.required_removed",
        category="input",
        suggestion="Usually backwards-compatible; check behavior and refresh the baseline if intentional.",
    ),
    "input.removed": AdviceRule(
        code="input.removed",
        category="input",
        suggestion="Keep accepting the old input as deprecated, or update all callers that may still send it.",
    ),
    "input.rename_candidate": AdviceRule(
        code="input.rename_candidate",
        category="input",
        suggestion="This rename is inferred. Verify it in source code, then keep an alias for the old input or update every caller together.",
    ),
    "input.optional_added": AdviceRule(
        code="input.optional_added",
        category="input",
        suggestion="Usually backwards-compatible; document the default behavior and refresh the baseline if intentional.",
    ),
    "schema.type_changed": AdviceRule(
        code="schema.type_changed",
        category="schema",
        suggestion="Keep the old type during a transition, or add coercion/validation so older calls fail clearly.",
    ),
    "schema.type_narrowed": AdviceRule(
        code="schema.type_narrowed",
        category="schema",
        suggestion="Keep accepting the previous type set during migration, or update callers and validators together.",
    ),
    "schema.type_widened": AdviceRule(
        code="schema.type_widened",
        category="schema",
        suggestion="Usually safe for inputs; check downstream output consumers if more result types can now appear.",
    ),
    "schema.enum_narrowed": AdviceRule(
        code="schema.enum_narrowed",
        category="schema",
        suggestion="Keep accepting old enum values with aliases during migration, or update prompts and callers to the new allowed set.",
    ),
    "schema.enum_changed": AdviceRule(
        code="schema.enum_changed",
        category="schema",
        suggestion="Check prompts, validation, and tests for old enum values before refreshing the baseline.",
    ),
    "schema.enum_widened": AdviceRule(
        code="schema.enum_widened",
        category="schema",
        suggestion="Usually safe for inputs; check output consumers if the tool may now return additional enum values.",
    ),
    "schema.nullability_removed": AdviceRule(
        code="schema.nullability_removed",
        category="schema",
        suggestion="Keep accepting null during migration, or update callers and validation to stop sending null.",
    ),
    "schema.nullability_added": AdviceRule(
        code="schema.nullability_added",
        category="schema",
        suggestion="Usually safe for inputs; check downstream output parsers if null can now appear.",
    ),
    "schema.required_added": AdviceRule(
        code="schema.required_added",
        category="schema",
        suggestion="Avoid making nested fields required until existing callers can provide them.",
    ),
    "schema.required_removed": AdviceRule(
        code="schema.required_removed",
        category="schema",
        suggestion="Usually safe for inputs; check output consumers that assumed this field was always present.",
    ),
    "schema.property_removed": AdviceRule(
        code="schema.property_removed",
        category="schema",
        suggestion="Keep returning this field until downstream parsers and tests no longer depend on it.",
    ),
    "schema.property_rename_candidate": AdviceRule(
        code="schema.property_rename_candidate",
        category="schema",
        suggestion="This rename is inferred. Verify it in source code, then support both field names during migration or update downstream parsers.",
    ),
    "schema.property_added": AdviceRule(
        code="schema.property_added",
        category="schema",
        suggestion="Usually safe, but check strict downstream parsers before accepting the new output shape.",
    ),
    "schema.default_added": AdviceRule(
        code="schema.default_added",
        category="schema",
        suggestion="Document the default because it can change agent behavior even when calls still validate.",
    ),
    "schema.default_removed": AdviceRule(
        code="schema.default_removed",
        category="schema",
        suggestion="Keep the old default in code or update callers so omitted values remain intentional.",
    ),
    "schema.default_changed": AdviceRule(
        code="schema.default_changed",
        category="schema",
        suggestion="Review behavior and tests because callers that omit the value will now get different behavior.",
    ),
    "schema.constraint_narrowed": AdviceRule(
        code="schema.constraint_narrowed",
        category="schema",
        suggestion="Keep old values valid during rollout, or update callers and prompts to stay inside the new constraint.",
    ),
    "schema.constraint_relaxed": AdviceRule(
        code="schema.constraint_relaxed",
        category="schema",
        suggestion="Usually backwards-compatible for inputs; add tests for the newly accepted range.",
    ),
    "schema.constraint_changed": AdviceRule(
        code="schema.constraint_changed",
        category="schema",
        suggestion="Review validation and generated calls because this constraint changed in a way the scanner cannot order safely.",
    ),
    "schema.additional_properties_restricted": AdviceRule(
        code="schema.additional_properties_restricted",
        category="schema",
        suggestion="Keep accepting unknown properties temporarily, or update callers that may send extra fields.",
    ),
    "schema.additional_properties_relaxed": AdviceRule(
        code="schema.additional_properties_relaxed",
        category="schema",
        suggestion="Usually safe for inputs; check whether accepting extra fields has security or routing implications.",
    ),
    "schema.additional_properties_changed": AdviceRule(
        code="schema.additional_properties_changed",
        category="schema",
        suggestion="Review callers and validators because extra-field handling changed.",
    ),
    "schema.items_changed": AdviceRule(
        code="schema.items_changed",
        category="schema",
        suggestion="Check array callers and output parsers because element schemas changed.",
    ),
    "schema.composition_narrowed": AdviceRule(
        code="schema.composition_narrowed",
        category="schema",
        suggestion="Keep old union/composition variants accepted during migration, or update callers to the remaining variants.",
    ),
    "schema.composition_widened": AdviceRule(
        code="schema.composition_widened",
        category="schema",
        suggestion="Usually safe for inputs; check downstream parsing if outputs may now take more shapes.",
    ),
    "schema.composition_changed": AdviceRule(
        code="schema.composition_changed",
        category="schema",
        suggestion="Review union/composition semantics manually because the shape changed in a way the scanner cannot prove safe.",
    ),
    "environment.package_version_changed": AdviceRule(
        code="environment.package_version_changed",
        category="environment",
        suggestion="Review dependency release notes and rerun snapshots/tests because generated tool schemas may have changed.",
    ),
}


DEFAULT_ADVICE_RULE = AdviceRule(
    code="unknown",
    category="unknown",
    suggestion="Review this drift before refreshing the baseline.",
)


def advice_for(code: str) -> AdviceRule:
    return ADVICE_RULES.get(code, DEFAULT_ADVICE_RULE)


def resolve_advice(
    code: str,
    override: Any = None,
    agent_guidance: Optional[str] = None,
) -> AdviceRule:
    base = advice_for(code)
    override_mapping = override if isinstance(override, Mapping) else None
    override_suggestion = override if isinstance(override, str) else None

    suggestion = override_suggestion or _override_attr(override, override_mapping, "suggestion")
    kind = _override_attr(override, override_mapping, "kind")
    category = _override_attr(override, override_mapping, "category")
    guidance = _override_attr(override, override_mapping, "agent_guidance")

    return AdviceRule(
        code=code,
        category=str(category or base.category),
        suggestion=str(suggestion or base.suggestion),
        kind=str(kind or base.kind),
        agent_guidance=str(guidance or agent_guidance or base.agent_guidance),
    )


def _override_attr(override: Any, override_mapping: Optional[Mapping[str, Any]], name: str) -> Any:
    if override_mapping is not None:
        return override_mapping.get(name)
    return getattr(override, name, None)
