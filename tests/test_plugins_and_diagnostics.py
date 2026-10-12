import json
from pathlib import Path

from agent_tool_drift.adapters.base import AdapterContext, ToolAdapter
from agent_tool_drift.cli import main
from agent_tool_drift.config import parse_config
from agent_tool_drift.models import ToolContract
from agent_tool_drift.scanner import scan_project


class DummyPluginAdapter(ToolAdapter):
    name = "dummy-plugin"

    def scan(self, context: AdapterContext) -> list[ToolContract]:
        return [
            ToolContract(
                name="dummy_tool",
                kind="dummy",
                source_path="dummy.py",
                source_line=1,
                description="Dummy plugin tool.",
                input_schema={"type": "object", "properties": {}, "required": []},
                metadata={"adapter": self.name},
            )
        ]


class DummyEntryPoint:
    name = "dummy"

    def load(self):
        return DummyPluginAdapter


class DummyEntryPoints(list):
    def select(self, group: str):
        if group == "agent_tool_drift.adapters":
            return self
        return []


def test_external_adapter_entry_point_can_be_loaded(monkeypatch, tmp_path: Path) -> None:
    import agent_tool_drift.adapters.registry as registry

    monkeypatch.setattr(registry.importlib.metadata, "entry_points", lambda: DummyEntryPoints([DummyEntryPoint()]))
    config = parse_config(
        {
            "python": {"enabled": False},
            "manifests": {"enabled": False},
            "openapi": {"enabled": False},
            "plugins": {"enabled": True, "include": ["dummy"]},
        }
    )

    snapshot = scan_project(tmp_path, config=config)

    assert [tool.name for tool in snapshot.tools] == ["dummy_tool"]
    assert snapshot.tools[0].metadata["adapter"] == "dummy-plugin"


def test_adapters_cli_outputs_json(tmp_path: Path) -> None:
    output = tmp_path / "adapters.json"

    code = main(["adapters", "examples/python_agent", "--format", "json"])

    assert code == 0


def test_adapters_cli_reports_openai_agents_status(capsys) -> None:
    code = main(["adapters", "examples/openai_agents_agent", "--format", "json"])

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert code == 0
    assert any(item["name"] == "openai-agents-static" and item["enabled"] for item in data["adapters"])


def test_doctor_cli_summarizes_project(capsys) -> None:
    code = main(["doctor", "examples/python_agent", "--format", "json"])

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert code == 0
    assert data["tool_count"] == 4
    assert data["tools_by_kind"]["python"] == 2


def test_snapshot_and_diff_html_outputs(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    html = tmp_path / "report.html"
    snapshot_html = tmp_path / "snapshot.html"

    assert main(["snapshot", "examples/python_agent", "-o", str(before)]) == 0
    assert main(["snapshot", "examples/updated_python_agent", "-o", str(after)]) == 0
    assert main(["snapshot", "examples/python_agent", "--format", "html", "-o", str(snapshot_html)]) == 0
    assert main(["diff", str(before), str(after), "--format", "html", "-o", str(html)]) == 0

    assert "<!doctype html>" in html.read_text(encoding="utf-8")
    assert "Agent Tool Drift Snapshot" in snapshot_html.read_text(encoding="utf-8")
