
"""Deterministic workflow-to-tool dependency mapping."""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set

from .config import AgentToolDriftConfig


@dataclass
class Workflow:
    """A workflow and the tools and tests associated with it."""

    name: str
    tools: Set[str] = field(default_factory=set)
    regression_tests: Set[str] = field(default_factory=set)


@dataclass
class ImpactResult:
    """Workflows and tests affected by changed tools."""

    changed_tools: List[str]
    affected_workflows: List[str]
    selected_tests: List[str]


class DependencyGraph:
    """Maps tools to workflows and selects relevant regression tests."""

    def __init__(self, workflows: Iterable[Workflow] = ()) -> None:
        self._workflows: Dict[str, Workflow] = {}

        for workflow in workflows:
            self.add_workflow(workflow)

    @classmethod
    def from_config(cls, config: AgentToolDriftConfig) -> "DependencyGraph":
        """Build a dependency graph from parsed project configuration."""
        workflows = [
            Workflow(
                name=name,
                tools=set(workflow.tools),
                regression_tests=set(workflow.regression_tests),
            )
            for name, workflow in config.workflows.items()
        ]
        return cls(workflows)

    def add_workflow(self, workflow: Workflow) -> None:
        """Register or replace a workflow by name."""
        if not workflow.name.strip():
            raise ValueError("Workflow name must not be empty.")

        self._workflows[workflow.name] = Workflow(
            name=workflow.name,
            tools=set(workflow.tools),
            regression_tests=set(workflow.regression_tests),
        )

    def analyze_impact(self, changed_tools: Iterable[str]) -> ImpactResult:
        """Return workflows and tests that depend on changed tools."""
        changed = set(changed_tools)
        affected = [
            workflow
            for workflow in self._workflows.values()
            if workflow.tools & changed
        ]

        return ImpactResult(
            changed_tools=sorted(changed),
            affected_workflows=sorted(
                workflow.name for workflow in affected
            ),
            selected_tests=sorted({
                test
                for workflow in affected
                for test in workflow.regression_tests
            }),
        )
