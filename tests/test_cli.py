import json
from pathlib import Path
from typing import Any

from agent_tool_drift.cli import main


def test_snapshot_cli_writes_json(tmp_path: Path) -> None:
    output = tmp_path / "snapshot.json"

    code = main(["snapshot", "examples/python_agent", "-o", str(output)])

    assert code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert any(tool["name"] == "search_web" for tool in data["tools"])


def test_diff_cli_returns_breaking_exit_code(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    report = tmp_path / "report.md"

    assert main(["snapshot", "examples/python_agent", "-o", str(before)]) == 0
    assert main(["snapshot", "examples/updated_python_agent", "-o", str(after)]) == 0
    code = main(["diff", str(before), str(after), "-o", str(report), "--fail-on-breaking"])

    assert code == 2
    assert "BREAKING" in report.read_text(encoding="utf-8")


def test_diff_cli_reports_missing_snapshot_without_traceback(tmp_path: Path, capsys: Any) -> None:
    code = main(["diff", str(tmp_path / "missing-old.json"), str(tmp_path / "missing-new.json")])

    captured = capsys.readouterr()
    assert code == 1
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err


def test_diff_cli_reports_malformed_snapshot_without_traceback(tmp_path: Path, capsys: Any) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text('{"tools": [42]}', encoding="utf-8")
    after.write_text('{"tools": []}', encoding="utf-8")

    code = main(["diff", str(before), str(after)])

    captured = capsys.readouterr()
    assert code == 1
    assert "Snapshot tool entries must be objects" in captured.err
    assert "Traceback" not in captured.err


def test_check_cli_creates_missing_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "snapshot.json"
    report = tmp_path / "report.sarif"

    code = main(["check", "examples/python_agent", "--baseline", str(baseline), "--format", "sarif", "-o", str(report)])

    assert code == 0
    assert baseline.exists()
    assert json.loads(report.read_text(encoding="utf-8"))["runs"][0]["results"] == []


def test_check_cli_default_baseline_is_project_relative(tmp_path: Path, monkeypatch: Any) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "tools.py").write_text(
        """
def tool(func):
    return func


@tool
def ping(name: str) -> str:
    return name
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    code = main(["check", str(project)])

    assert code == 0
    assert (project / ".agent-tool-drift" / "snapshot.json").exists()
    assert not (tmp_path / ".agent-tool-drift" / "snapshot.json").exists()


def test_check_cli_updates_existing_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "snapshot.json"

    assert main(["snapshot", "examples/python_agent", "-o", str(baseline)]) == 0
    code = main(["check", "examples/updated_python_agent", "--baseline", str(baseline), "--update-baseline"])

    assert code == 0
    data = json.loads(baseline.read_text(encoding="utf-8"))
    assert any(tool["version"] == "2.0.0" for tool in data["tools"] if tool["name"] == "search_web")
