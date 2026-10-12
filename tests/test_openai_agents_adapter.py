from pathlib import Path

from agent_tool_drift.scanner import scan_project


def test_openai_agents_adapter_detects_function_tools() -> None:
    snapshot = scan_project("examples/openai_agents_agent")

    names = {tool.name for tool in snapshot.tools}

    assert names == {"weather_lookup", "lookup_user"}

    weather = next(tool for tool in snapshot.tools if tool.name == "weather_lookup")
    assert weather.kind == "openai-agents"
    assert weather.description == "Get current weather for a city."
    assert weather.input_schema["required"] == ["city"]
    assert weather.input_schema["properties"]["city"]["type"] == "string"
    assert weather.input_schema["properties"]["units"]["type"] == "string"
    assert weather.output_schema["type"] == "object"
    assert weather.metadata["name_override"] == "weather_lookup"
    assert weather.metadata["description_override"] == "Get current weather for a city."

    user = next(tool for tool in snapshot.tools if tool.name == "lookup_user")
    assert user.input_schema["required"] == ["user_id"]
    assert "ctx" not in user.input_schema["properties"]
    assert user.metadata["async"] is True
    assert user.metadata["defer_loading"] is True


def test_openai_agents_adapter_recognizes_module_alias_import(tmp_path: Path) -> None:
    (tmp_path / "agent-tool-drift.yaml").write_text(
        """
python:
  enabled: false
manifests:
  enabled: false
openapi:
  enabled: false
openai_agents:
  enabled: true
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "tools.py").write_text(
        "import agents as ag\n"
        "@ag.function_tool(name_override='alias_tool')\n"
        "def search(query: str) -> str:\n"
        "    '''Search with an aliased import.'''\n"
        "    return query\n",
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)

    assert [tool.name for tool in snapshot.tools] == ["alias_tool"]
