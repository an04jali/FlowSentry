
from agent_tool_drift.dependency_graph import DependencyGraph, Workflow
from agent_tool_drift.diff import ContractChange, DiffResult
from agent_tool_drift.impact import analyze_change_impact


def test_breaking_change_selects_affected_workflow_tests():
    diff = DiffResult(
        before_root="before",
        after_root="after",
        changes=[
            ContractChange(
                severity="BREAKING",
                code="input.removed",
                tool="customer_search",
                message="Input 'query' was removed.",
            ),
            ContractChange(
                severity="INFO",
                code="tool.added",
                tool="new_tool",
                message="A new tool was added.",
            ),
        ],
    )

    graph = DependencyGraph([
        Workflow(
            name="customer_support",
            tools={"customer_search"},
            regression_tests={"test_search", "test_support"},
        ),
        Workflow(
            name="billing",
            tools={"invoice_lookup"},
            regression_tests={"test_billing"},
        ),
    ])

    report = analyze_change_impact(diff, graph)

    assert report.changed_tools == ["customer_search", "new_tool"]
    assert report.breaking_tools == ["customer_search"]
    assert report.affected_workflows == ["customer_support"]
    assert report.selected_tests == ["test_search", "test_support"]


def test_environment_changes_are_not_treated_as_tool_changes():
    diff = DiffResult(
        before_root="before",
        after_root="after",
        changes=[
            ContractChange(
                severity="INFO",
                code="environment.package_version_changed",
                tool="package:requests",
                message="Package version changed.",
            ),
        ],
    )

    graph = DependencyGraph([
        Workflow(
            name="customer_support",
            tools={"customer_search"},
            regression_tests={"test_search"},
        ),
    ])

    report = analyze_change_impact(diff, graph)

    assert report.changed_tools == []
    assert report.breaking_tools == []
    assert report.affected_workflows == []
    assert report.selected_tests == []


def test_multiple_changes_to_one_tool_are_deduplicated():
    diff = DiffResult(
        before_root="before",
        after_root="after",
        changes=[
            ContractChange(
                severity="BREAKING",
                code="input.removed",
                tool="customer_search",
                message="Input query was removed.",
            ),
            ContractChange(
                severity="BREAKING",
                code="input.required_added",
                tool="customer_search",
                message="Input search_term became required.",
            ),
        ],
    )

    graph = DependencyGraph([
        Workflow(
            name="customer_support",
            tools={"customer_search"},
            regression_tests={"test_search"},
        ),
    ])

    report = analyze_change_impact(diff, graph)

    assert report.changed_tools == ["customer_search"]
    assert report.breaking_tools == ["customer_search"]
    assert report.selected_tests == ["test_search"]
