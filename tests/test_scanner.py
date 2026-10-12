from pathlib import Path

from agent_tool_drift.scanner import scan_project


def test_scan_python_manifest_and_openapi_examples() -> None:
    root = Path("examples/python_agent")

    snapshot = scan_project(root)
    names = {tool.name for tool in snapshot.tools}

    assert {"search_web", "summarize", "lookup_customer", "get_ticket"} <= names

    search = next(tool for tool in snapshot.tools if tool.name == "search_web")
    assert search.kind == "python"
    assert search.input_schema["properties"]["query"]["type"] == "string"
    assert search.input_schema["properties"]["top_k"]["type"] == "integer"
    assert search.input_schema["required"] == ["query"]
    assert search.output_schema["type"] == "array"

    manifest = next(tool for tool in snapshot.tools if tool.name == "lookup_customer")
    assert manifest.kind == "manifest"
    assert manifest.input_schema["required"] == ["customer_id"]

    openapi = next(tool for tool in snapshot.tools if tool.name == "get_ticket")
    assert openapi.kind == "openapi"
    assert openapi.input_schema["properties"]["ticket_id"]["metadata"]["in"] == "path"


def test_scan_does_not_import_project_code(tmp_path: Path) -> None:
    (tmp_path / "tools.py").write_text(
        "raise RuntimeError('import side effect')\n"
        "from imaginary import tool\n"
        "@tool\n"
        "def hidden(query: str) -> str:\n"
        "    return query\n",
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)

    assert [tool.name for tool in snapshot.tools] == ["hidden"]


def test_python_scanner_records_literal_defaults(tmp_path: Path) -> None:
    (tmp_path / "tools.py").write_text(
        "from imaginary import tool\n"
        "@tool\n"
        "def search(query: str, limit: int = 5, mode: str | None = None) -> str:\n"
        "    return query\n",
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tool = next(tool for tool in snapshot.tools if tool.name == "search")

    assert tool.input_schema["required"] == ["query"]
    assert tool.input_schema["properties"]["limit"]["default"] == 5
    assert tool.input_schema["properties"]["mode"]["default"] is None


def test_python_scanner_reads_annotated_inner_types(tmp_path: Path) -> None:
    (tmp_path / "tools.py").write_text(
        "from typing import Annotated\n"
        "from imaginary import tool\n"
        "@tool\n"
        "def search(query: Annotated[str, 'Search query'], limit: Annotated[int, 'Limit'] = 5) -> str:\n"
        "    return query\n",
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tool = next(tool for tool in snapshot.tools if tool.name == "search")

    assert tool.input_schema["properties"]["query"]["type"] == "string"
    assert tool.input_schema["properties"]["limit"]["type"] == "integer"
    assert tool.input_schema["properties"]["limit"]["default"] == 5


def test_scan_yaml_manifest_and_openapi(tmp_path: Path) -> None:
    (tmp_path / "tools.yaml").write_text(
        """
tools:
  - name: yaml_lookup
    description: Look up an item from a YAML manifest.
    inputSchema:
      type: object
      properties:
        item_id:
          type: string
      required:
        - item_id
    outputSchema:
      type: object
      properties:
        title:
          type: string
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "openapi.yaml").write_text(
        """
openapi: 3.0.0
info:
  title: YAML API
  version: 1.0.0
paths:
  /records/{record_id}:
    get:
      operationId: get_record
      summary: Get a record.
      parameters:
        - name: record_id
          in: path
          required: true
          schema:
            type: string
      responses:
        "200":
          description: Record response
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    names = {tool.name for tool in snapshot.tools}

    assert {"yaml_lookup", "get_record"} <= names
    manifest = next(tool for tool in snapshot.tools if tool.name == "yaml_lookup")
    openapi = next(tool for tool in snapshot.tools if tool.name == "get_record")
    assert manifest.input_schema["required"] == ["item_id"]
    assert openapi.source_path == "openapi.yaml"
    assert openapi.input_schema["properties"]["record_id"]["metadata"]["in"] == "path"


def test_scan_top_level_manifest_and_literal_none(tmp_path: Path) -> None:
    (tmp_path / "tools.yaml").write_text(
        """
name: top_level_lookup
description: Single-tool manifest.
input_schema:
  type: object
  properties:
    item_id:
      type: string
  required:
    - item_id
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "tools.py").write_text(
        "from typing import Literal\n"
        "from imaginary import tool\n"
        "@tool\n"
        "def choose_mode(mode: Literal[None, 'auto']) -> str:\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    top_level = next(tool for tool in snapshot.tools if tool.name == "top_level_lookup")
    literal_tool = next(tool for tool in snapshot.tools if tool.name == "choose_mode")

    assert top_level.kind == "manifest"
    assert top_level.input_schema["required"] == ["item_id"]
    assert literal_tool.input_schema["properties"]["mode"]["enum"] == [None, "auto"]


def test_manifest_with_malformed_required_does_not_drop_all_tools(tmp_path: Path) -> None:
    (tmp_path / "tools.yaml").write_text(
        """
tools:
  - name: bad_required
    input_schema:
      type: object
      properties:
        query:
          type: string
      required: true
  - name: good_required
    input_schema:
      type: object
      properties:
        item_id:
          type: string
      required:
        - item_id
""".lstrip(),
        encoding="utf-8",
    )

    snapshot = scan_project(tmp_path)
    tools = {tool.name: tool for tool in snapshot.tools}

    assert tools["bad_required"].input_schema["required"] == []
    assert tools["good_required"].input_schema["required"] == ["item_id"]
    assert "adapter_errors" not in snapshot.environment
