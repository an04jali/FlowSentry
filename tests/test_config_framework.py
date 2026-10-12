import json
import sys
from pathlib import Path

from agent_tool_drift.cli import main
from agent_tool_drift.config import load_config, parse_config
from agent_tool_drift.scanner import scan_project


def test_parse_config_supports_custom_patterns_and_policy() -> None:
    config = parse_config(
        {
            "python": {
                "decorators": ["register_tool"],
                "include": ["agent/**/*.py"],
                "exclude": ["agent/private/**"],
            },
            "policy": {
                "fail_on": ["input.required_added"],
                "ignore": ["tool.description_changed"],
            },
            "openai_agents": {
                "enabled": True,
                "include": ["agents/**/*.py"],
                "exclude": ["agents/private/**"],
            },
            "advice": {
                "agent_guidance": "Inspect project-specific callers before editing.",
                "overrides": {
                    "input.required_added": {
                        "suggestion": "Project rule: new arguments must ship as optional first.",
                        "kind": "project",
                        "category": "input",
                    },
                    "tool.removed": "Project rule: keep deleted tools for one release.",
                },
            },
        }
    )

    assert config.python.decorators == ("register_tool",)
    assert config.python.include == ("agent/**/*.py",)
    assert config.python.exclude == ("agent/private/**",)
    assert config.policy.fail_on == ("input.required_added",)
    assert config.policy.ignore == ("tool.description_changed",)
    assert config.openai_agents.enabled is True
    assert config.openai_agents.include == ("agents/**/*.py",)
    assert config.openai_agents.exclude == ("agents/private/**",)
    assert config.advice.agent_guidance == "Inspect project-specific callers before editing."
    assert config.advice.overrides["input.required_added"].suggestion == "Project rule: new arguments must ship as optional first."
    assert config.advice.overrides["input.required_added"].kind == "project"
    assert config.advice.overrides["tool.removed"].suggestion == "Project rule: keep deleted tools for one release."


def test_scan_project_uses_custom_config_file(tmp_path: Path) -> None:
    (tmp_path / "custom_tools.py").write_text(
        "from imaginary import register_tool\n"
        "@register_tool(name='custom_search')\n"
        "def search(query: str) -> str:\n"
        "    return query\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "agent-tool-drift.yaml"
    config_path.write_text(
        """
python:
  decorators:
    - register_tool
manifests:
  enabled: false
openapi:
  enabled: false
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path, config_path=config_path)

    assert [tool.name for tool in snapshot.tools] == ["custom_search"]
    assert snapshot.environment["config"]["source_path"] == str(config_path.resolve())


def test_scan_project_resolves_relative_config_path_from_project_root(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "tools.py").write_text(
        "from imaginary import register_tool\n"
        "@register_tool\n"
        "def custom(query: str) -> str:\n"
        "    return query\n",
        encoding="utf-8",
    )
    config_path = project / "agent-tool-drift.yaml"
    config_path.write_text(
        """
python:
  decorators:
    - register_tool
manifests:
  enabled: false
openapi:
  enabled: false
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    snapshot = scan_project(project, config_path="agent-tool-drift.yaml")

    assert [tool.name for tool in snapshot.tools] == ["custom"]
    assert snapshot.environment["config"]["source_path"] == str(config_path.resolve())


def test_project_relative_config_wins_over_same_named_cwd_config(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "tools.py").write_text(
        "from imaginary import register_tool\n"
        "@register_tool\n"
        "def custom(query: str) -> str:\n"
        "    return query\n",
        encoding="utf-8",
    )
    cwd_config = tmp_path / "agent-tool-drift.yaml"
    cwd_config.write_text(
        """
python:
  decorators:
    - wrong_tool
manifests:
  enabled: false
openapi:
  enabled: false
""".lstrip(),
        encoding="utf-8",
    )
    project_config = project / "agent-tool-drift.yaml"
    project_config.write_text(
        """
python:
  decorators:
    - register_tool
manifests:
  enabled: false
openapi:
  enabled: false
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    snapshot = scan_project(project, config_path="agent-tool-drift.yaml")

    assert [tool.name for tool in snapshot.tools] == ["custom"]
    assert snapshot.environment["config"]["source_path"] == str(project_config.resolve())


def test_init_cli_creates_default_config(tmp_path: Path) -> None:
    config_path = tmp_path / "agent-tool-drift.yaml"

    code = main(["init", "-o", str(config_path)])

    assert code == 0
    config = load_config(config_path)
    assert "tool" in config.python.decorators


def test_cli_reports_malformed_config_without_traceback(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "agent-tool-drift.yaml"
    config_path.write_text("python:\n  enabled: [\n", encoding="utf-8")

    code = main(["snapshot", "examples/python_agent", "--config", str(config_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert "Error: Failed to parse configuration file" in captured.err
    assert "Traceback" not in captured.err


def test_parse_config_handles_missing_and_invalid_mcp_timeout() -> None:
    config = parse_config(
        {
            "mcp": {
                "servers": {
                    "example": {
                        "command": ["python", "server.py"],
                        "timeout": None,
                    }
                }
            }
        }
    )

    assert config.mcp.servers["example"].timeout == 10.0

    try:
        parse_config(
            {
                "mcp": {
                    "servers": {
                        "bad": {
                            "command": ["python", "server.py"],
                            "timeout": "soon",
                        }
                    }
                }
            }
        )
    except ValueError as exc:
        assert "mcp.servers.bad.timeout" in str(exc)
    else:
        raise AssertionError("Expected invalid MCP timeout to raise ValueError.")


def test_mcp_snapshot_can_use_configured_server(tmp_path: Path) -> None:
    server = Path("examples/mcp_server/mock_server.py").resolve()
    config_path = tmp_path / "agent-tool-drift.json"
    config_path.write_text(
        json.dumps(
            {
                "mcp": {
                    "servers": {
                        "example": {
                            "command": [sys.executable, str(server)],
                            "timeout": 3,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "mcp.json"

    code = main(["mcp-snapshot", "--config", str(config_path), "--server", "example", "-o", str(output)])

    assert code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["root"] == "mcp://stdio/example"
    assert {tool["name"] for tool in data["tools"]} == {"search_docs", "summarize_doc"}


def test_diff_cli_can_apply_policy_ignore_and_fail_on(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    config_path = tmp_path / "agent-tool-drift.yaml"
    report = tmp_path / "report.json"

    assert main(["snapshot", "examples/python_agent", "-o", str(before)]) == 0
    assert main(["snapshot", "examples/updated_python_agent", "-o", str(after)]) == 0
    config_path.write_text(
        """
policy:
  fail_on:
    - input.required_added
  ignore:
    - tool.description_changed
advice:
  overrides:
    input.required_added:
      suggestion: Project-specific rollout advice.
      kind: project
""".lstrip(),
        encoding="utf-8",
    )

    code = main(
        [
            "diff",
            str(before),
            str(after),
            "--config",
            str(config_path),
            "--format",
            "json",
            "-o",
            str(report),
            "--fail-on-policy",
        ]
    )

    data = json.loads(report.read_text(encoding="utf-8"))
    codes = {change["code"] for change in data["changes"]}
    assert code == 2
    assert "input.required_added" in codes
    assert "tool.description_changed" not in codes
    required_added = next(change for change in data["changes"] if change["code"] == "input.required_added")
    assert required_added["advice"] == "Project-specific rollout advice."
    assert required_added["advice_kind"] == "project"

def test_parse_config_supports_workflow_dependencies() -> None:
    config = parse_config(
        {
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
        }
    )

    assert config.workflows["customer_support"].tools == (
        "customer_search",
        "ticket_summary",
    )
    assert config.workflows["customer_support"].regression_tests == (
        "tests/test_customer_search.py",
        "tests/test_ticket_summary.py",
    )
    assert config.workflows["billing"].tools == ("invoice_lookup",)


def test_parse_config_defaults_to_no_workflows() -> None:
    config = parse_config({})

    assert config.workflows == {}


def test_parse_config_rejects_invalid_workflow_definition() -> None:
    try:
        parse_config(
            {
                "workflows": {
                    "customer_support": {
                        "tools": "customer_search",
                        "regression_tests": ["tests/test_search.py"],
                    }
                }
            }
        )
    except ValueError as exc:
        assert "workflows.customer_support.tools" in str(exc)
    else:
        raise AssertionError("Expected invalid workflow configuration to raise ValueError.")
