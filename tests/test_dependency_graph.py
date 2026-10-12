
from agent_tool_drift.dependency_graph import DependencyGraph, Workflow


def test_changed_tool_selects_affected_workflows_and_tests():
    graph = DependencyGraph([
        Workflow(
            name="customer_support",
            tools={"customer_search", "ticket_summary"},
            regression_tests={"test_customer_search", "test_ticket_summary"},
        ),
        Workflow(
            name="billing",
            tools={"invoice_lookup"},
            regression_tests={"test_invoice_lookup"},
        ),
    ])

    result = graph.analyze_impact({"customer_search"})

    assert result.changed_tools == ["customer_search"]
    assert result.affected_workflows == ["customer_support"]
    assert result.selected_tests == [
        "test_customer_search",
        "test_ticket_summary",
    ]


def test_multiple_changed_tools_deduplicate_tests():
    graph = DependencyGraph([
        Workflow(
            name="support",
            tools={"search", "summarize"},
            regression_tests={"test_support", "test_search"},
        ),
    ])

    result = graph.analyze_impact({"search", "summarize"})

    assert result.affected_workflows == ["support"]
    assert result.selected_tests == ["test_search", "test_support"]


def test_unknown_changed_tool_has_no_impact():
    graph = DependencyGraph([
        Workflow(
            name="billing",
            tools={"invoice_lookup"},
            regression_tests={"test_invoice"},
        ),
    ])

    result = graph.analyze_impact({"unknown_tool"})

    assert result.affected_workflows == []
    assert result.selected_tests == []


def test_empty_workflow_name_is_rejected():
    graph = DependencyGraph()

    try:
        graph.add_workflow(Workflow(name=" ", tools={"search"}))
        assert False, "Expected ValueError for an empty workflow name"
    except ValueError as exc:
        assert "Workflow name" in str(exc)
from agent_tool_drift.config import parse_config


def test_dependency_graph_can_be_built_from_config():
    config = parse_config({
        "workflows": {
            "customer_support": {
                "tools": ["customer_search", "ticket_summary"],
                "regression_tests": [
                    "tests/test_customer_search.py",
                    "tests/test_ticket_summary.py",
                ],
            },
            "billing": {
                "tools": ["invoice_lookup"],
                "regression_tests": ["tests/test_billing.py"],
            },
        }
    })

    graph = DependencyGraph.from_config(config)
    impact = graph.analyze_impact(["customer_search"])

    assert impact.affected_workflows == ["customer_support"]
    assert impact.selected_tests == [
        "tests/test_customer_search.py",
        "tests/test_ticket_summary.py",
    ]
