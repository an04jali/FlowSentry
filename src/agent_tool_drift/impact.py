
"""Connect contract diff results to workflow dependency analysis."""

from dataclasses import dataclass
from typing import List

from .dependency_graph import DependencyGraph, ImpactResult
from .diff import DiffResult


@dataclass(frozen=True)
class ChangeImpactReport:
    """Contract changes and their workflow-level impact."""

    changed_tools: List[str]
    breaking_tools: List[str]
    affected_workflows: List[str]
    selected_tests: List[str]


def analyze_change_impact(
    diff_result: DiffResult,
    dependency_graph: DependencyGraph,
) -> ChangeImpactReport:
    """Map detected contract changes to workflows and regression tests."""

    changed_tools = {
        change.tool
        for change in diff_result.changes
        if not change.tool.startswith("package:")
    }

    breaking_tools = {
        change.tool
        for change in diff_result.changes
        if change.severity == "BREAKING"
        and not change.tool.startswith("package:")
    }

    impact: ImpactResult = dependency_graph.analyze_impact(changed_tools)

    return ChangeImpactReport(
        changed_tools=sorted(changed_tools),
        breaking_tools=sorted(breaking_tools),
        affected_workflows=impact.affected_workflows,
        selected_tests=impact.selected_tests,
    )
