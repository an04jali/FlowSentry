from pathlib import Path

from agent_tool_drift.scanner import scan_project


def test_langchain_adapter_detects_tool_decorator_and_structured_tool() -> None:
    snapshot = scan_project("examples/langchain_agent")

    names = {tool.name for tool in snapshot.tools}

    assert names == {"customer_search", "ticket_summary"}

    customer_search = next(tool for tool in snapshot.tools if tool.name == "customer_search")
    assert customer_search.kind == "langchain"
    assert customer_search.description == "Search customer records."
    assert customer_search.input_schema["required"] == ["query"]
    assert customer_search.input_schema["properties"]["limit"]["type"] == "integer"
    assert customer_search.output_schema["type"] == "object"

    ticket_summary = next(tool for tool in snapshot.tools if tool.name == "ticket_summary")
    assert ticket_summary.input_schema["required"] == ["ticket_id"]
    assert "runtime" not in ticket_summary.input_schema["properties"]
    assert ticket_summary.metadata["factory"] == "StructuredTool.from_function"


def test_langchain_adapter_recognizes_module_alias_import(tmp_path: Path) -> None:
    (tmp_path / "agent-tool-drift.yaml").write_text(
        """
python:
  enabled: false
manifests:
  enabled: false
openapi:
  enabled: false
langchain:
  enabled: true
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "tools.py").write_text(
        "import langchain.tools as lc_tools\n"
        "@lc_tools.tool('aliased_search')\n"
        "def search(query: str) -> str:\n"
        "    '''Search with an aliased import.'''\n"
        "    return query\n",
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)

    assert [tool.name for tool in snapshot.tools] == ["aliased_search"]
