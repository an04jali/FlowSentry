import json
from pathlib import Path

from agent_tool_drift.cli import main
from agent_tool_drift.diff import compare_snapshots
from agent_tool_drift.report import diff_sarif, github_annotations
from agent_tool_drift.scanner import scan_project


def test_diff_sarif_contains_github_compatible_shape() -> None:
    before = scan_project("examples/python_agent")
    after = scan_project("examples/updated_python_agent")
    result = compare_snapshots(before, after)

    data = json.loads(diff_sarif(result))

    assert data["version"] == "2.1.0"
    run = data["runs"][0]
    assert run["tool"]["driver"]["name"] == "agent-tool-drift"
    assert run["properties"]["compatibilityScore"] < 100
    assert run["properties"]["riskLevel"] in {"high", "critical"}
    assert any(item["ruleId"] == "input.required_added" for item in run["results"])
    breaking = next(item for item in run["results"] if item["ruleId"] == "input.required_added")
    assert breaking["level"] == "error"
    assert "Advice (heuristic):" in breaking["message"]["text"]
    assert breaking["properties"]["agentGuidance"]
    assert "partialFingerprints" in breaking


def test_github_annotations_escape_and_include_file_location() -> None:
    before = scan_project("examples/python_agent")
    after = scan_project("examples/updated_python_agent")
    result = compare_snapshots(before, after)

    text = github_annotations(result)

    assert "::error file=tools.py,line=5,title=input.required_added%3A search_web::Input 'top_k' became required." in text
    assert "Advice (heuristic):" in text
    assert "::warning" in text


def test_diff_cli_writes_sarif_and_annotations(tmp_path: Path, capsys) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    sarif = tmp_path / "report.sarif"

    assert main(["snapshot", "examples/python_agent", "-o", str(before)]) == 0
    assert main(["snapshot", "examples/updated_python_agent", "-o", str(after)]) == 0
    code = main(
        [
            "diff",
            str(before),
            str(after),
            "--format",
            "sarif",
            "-o",
            str(sarif),
            "--github-annotations",
            "--fail-on-breaking",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert json.loads(sarif.read_text(encoding="utf-8"))["version"] == "2.1.0"
    assert "::error" in captured.err
