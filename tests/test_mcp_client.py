import json
import sys
from pathlib import Path

from agent_tool_drift.cli import main
from agent_tool_drift.mcp_client import McpClientError, McpSnapshotOptions, snapshot_from_mcp_stdio


def test_snapshot_from_mcp_stdio_reads_paginated_tools(tmp_path: Path) -> None:
    server = _write_mock_mcp_server(tmp_path)

    snapshot = snapshot_from_mcp_stdio(
        McpSnapshotOptions(command=[sys.executable, str(server)], timeout=3.0, server_name="mock")
    )

    assert snapshot.root == "mcp://stdio/mock"
    assert [tool.name for tool in snapshot.tools] == ["search_docs", "summarize_doc"]
    search = snapshot.tools[0]
    assert search.kind == "mcp"
    assert search.version == "0.1.0"
    assert search.input_schema["required"] == ["query"]
    assert search.metadata["annotations"]["readOnlyHint"] is True


def test_mcp_snapshot_cli_writes_snapshot(tmp_path: Path) -> None:
    server = _write_mock_mcp_server(tmp_path)
    output = tmp_path / "mcp.json"

    code = main(["mcp-snapshot", "-o", str(output), "--server-name", "mock", "--", sys.executable, str(server)])

    assert code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["root"] == "mcp://stdio/mock"
    assert [tool["name"] for tool in data["tools"]] == ["search_docs", "summarize_doc"]


def test_mcp_client_rejects_non_list_tools_field(tmp_path: Path) -> None:
    server = tmp_path / "bad_mcp_server.py"
    server.write_text(
        r'''
import json
import sys


def send(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)


for line in sys.stdin:
    if not line.strip():
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "protocolVersion": message.get("params", {}).get("protocolVersion"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "bad-mcp", "version": "0.1.0"}
            }
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": {"name": "bad"}}})
'''.lstrip(),
        encoding="utf-8",
    )

    try:
        snapshot_from_mcp_stdio(McpSnapshotOptions(command=[sys.executable, str(server)], timeout=3.0))
    except McpClientError as exc:
        assert "non-list tools field" in str(exc)
    else:
        raise AssertionError("Expected malformed MCP tools/list response to raise McpClientError.")


def test_mcp_client_rejects_non_object_tool_entries(tmp_path: Path) -> None:
    server = _write_bad_tools_server(tmp_path, "[42]")

    try:
        snapshot_from_mcp_stdio(McpSnapshotOptions(command=[sys.executable, str(server)], timeout=3.0))
    except McpClientError as exc:
        assert "non-object tool entry" in str(exc)
    else:
        raise AssertionError("Expected malformed MCP tool entry to raise McpClientError.")


def _write_bad_tools_server(tmp_path: Path, tools_expression: str) -> Path:
    script = tmp_path / "bad_tools_server.py"
    script.write_text(
        f'''
import json
import sys


def send(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)


for line in sys.stdin:
    if not line.strip():
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({{
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {{
                "protocolVersion": message.get("params", {{}}).get("protocolVersion"),
                "capabilities": {{"tools": {{}}}},
                "serverInfo": {{"name": "bad-mcp", "version": "0.1.0"}}
            }}
        }})
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        send({{"jsonrpc": "2.0", "id": message["id"], "result": {{"tools": {tools_expression}}}}})
'''.lstrip(),
        encoding="utf-8",
    )
    return script


def _write_mock_mcp_server(tmp_path: Path) -> Path:
    script = tmp_path / "mock_mcp_server.py"
    script.write_text(
        r'''
import json
import sys


TOOLS_PAGE_1 = [
    {
        "name": "search_docs",
        "description": "Search local docs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"}
            },
            "required": ["query"]
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "results": {"type": "array"}
            }
        },
        "annotations": {"readOnlyHint": True}
    }
]

TOOLS_PAGE_2 = [
    {
        "name": "summarize_doc",
        "description": "Summarize one document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "doc_id": {"type": "string"},
                "style": {"type": "string"}
            },
            "required": ["doc_id"]
        }
    }
]


def send(payload):
    print(json.dumps(payload, separators=(",", ":")), flush=True)


for line in sys.stdin:
    if not line.strip():
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({
            "jsonrpc": "2.0",
            "id": message["id"],
            "result": {
                "protocolVersion": message.get("params", {}).get("protocolVersion"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-mcp", "version": "0.1.0"}
            }
        })
    elif method == "notifications/initialized":
        pass
    elif method == "tools/list":
        cursor = message.get("params", {}).get("cursor")
        result = {"tools": TOOLS_PAGE_2} if cursor == "page-2" else {"tools": TOOLS_PAGE_1, "nextCursor": "page-2"}
        send({"jsonrpc": "2.0", "id": message["id"], "result": result})
    elif "id" in message:
        send({
            "jsonrpc": "2.0",
            "id": message["id"],
            "error": {"code": -32601, "message": "Method not found"}
        })
'''.lstrip(),
        encoding="utf-8",
    )
    return script
