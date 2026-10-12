from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .models import Snapshot, ToolContract
from .schema import normalize_json_schema


DEFAULT_PROTOCOL_VERSION = "2025-06-18"


class McpClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class McpSnapshotOptions:
    command: Sequence[str]
    cwd: Optional[Path] = None
    timeout: float = 10.0
    protocol_version: str = DEFAULT_PROTOCOL_VERSION
    server_name: Optional[str] = None


@dataclass
class _ProcessState:
    process: subprocess.Popen[str]
    stdout: "queue.Queue[str]" = field(default_factory=queue.Queue)
    stderr_lines: List[str] = field(default_factory=list)


def snapshot_from_mcp_stdio(options: McpSnapshotOptions) -> Snapshot:
    if not options.command:
        raise McpClientError("MCP command cannot be empty.")

    state = _start_process(options)
    request_id = 1
    try:
        initialize = _request(
            state,
            request_id,
            "initialize",
            {
                "protocolVersion": options.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "agent-tool-drift", "version": "0.1.0"},
            },
            options.timeout,
        )
        request_id += 1
        server_info = _server_info(initialize)
        _notify(state, "notifications/initialized")

        tools: List[Mapping[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = _request(state, request_id, "tools/list", params, options.timeout)
            request_id += 1
            items = result.get("tools") if isinstance(result, Mapping) else None
            if not isinstance(items, list):
                raise McpClientError("MCP request 'tools/list' returned a non-list tools field.")
            if any(not isinstance(item, Mapping) for item in items):
                raise McpClientError("MCP request 'tools/list' returned a non-object tool entry.")
            tools.extend(items)
            cursor_value = result.get("nextCursor") if isinstance(result, Mapping) else None
            cursor = str(cursor_value) if cursor_value else None
            if not cursor:
                break

        server_name = options.server_name or str(server_info.get("name") or _command_name(options.command))
        contracts = [_tool_contract(server_name, tool, index, options.command, server_info) for index, tool in enumerate(tools)]
        return Snapshot(
            root=f"mcp://stdio/{server_name}",
            tools=contracts,
            environment={
                "mcp": {
                    "transport": "stdio",
                    "command": list(options.command),
                    "protocol_version": options.protocol_version,
                    "server_info": server_info,
                }
            },
        )
    finally:
        _stop_process(state)


def _start_process(options: McpSnapshotOptions) -> _ProcessState:
    try:
        process = subprocess.Popen(
            list(options.command),
            cwd=str(options.cwd) if options.cwd else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except OSError as exc:
        raise McpClientError(f"Failed to start MCP server: {exc}") from exc

    state = _ProcessState(process=process)
    assert process.stdout is not None
    assert process.stderr is not None
    threading.Thread(target=_read_stdout, args=(process.stdout, state.stdout), daemon=True).start()
    threading.Thread(target=_read_stderr, args=(process.stderr, state.stderr_lines), daemon=True).start()
    return state


def _read_stdout(stream: Any, output: "queue.Queue[str]") -> None:
    for line in stream:
        output.put(line)


def _read_stderr(stream: Any, output: List[str]) -> None:
    for line in stream:
        output.append(line.rstrip())


def _request(state: _ProcessState, request_id: int, method: str, params: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
    _write_message(state, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    response = _read_response(state, request_id, timeout)
    if "error" in response:
        raise McpClientError(f"MCP request '{method}' failed: {response['error']}")
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise McpClientError(f"MCP request '{method}' returned a non-object result.")
    return result


def _notify(state: _ProcessState, method: str, params: Optional[Mapping[str, Any]] = None) -> None:
    message: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    _write_message(state, message)


def _write_message(state: _ProcessState, message: Mapping[str, Any]) -> None:
    process = state.process
    if process.poll() is not None:
        raise McpClientError(_process_exited_message(state))
    assert process.stdin is not None
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read_response(state: _ProcessState, request_id: int, timeout: float) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if state.process.poll() is not None and state.stdout.empty():
            raise McpClientError(_process_exited_message(state))
        remaining = max(0.01, deadline - time.monotonic())
        try:
            line = state.stdout.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue
        message = _parse_message(line)
        if message is None:
            continue
        if message.get("id") == request_id:
            return message
        _handle_unsolicited_message(state, message)
    raise McpClientError(f"Timed out waiting for MCP response id {request_id}.")


def _parse_message(line: str) -> Optional[Mapping[str, Any]]:
    text = line.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None


def _handle_unsolicited_message(state: _ProcessState, message: Mapping[str, Any]) -> None:
    if "id" in message and "method" in message:
        _write_message(
            state,
            {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {"code": -32601, "message": "Method not found"},
            },
        )


def _tool_contract(
    server_name: str,
    tool: Mapping[str, Any],
    index: int,
    command: Sequence[str],
    server_info: Mapping[str, Any],
) -> ToolContract:
    name = str(tool.get("name") or f"unnamed_tool_{index}")
    input_schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    output_schema = tool.get("outputSchema") or tool.get("output_schema") or {}
    annotations = tool.get("annotations") if isinstance(tool.get("annotations"), Mapping) else {}
    title = tool.get("title")

    return ToolContract(
        name=name,
        kind="mcp",
        source_path=f"mcp://stdio/{server_name}/{name}",
        source_line=None,
        version=_string_or_none(server_info.get("version")),
        description=str(tool.get("description") or title or ""),
        input_schema=normalize_json_schema(dict(input_schema) if isinstance(input_schema, Mapping) else {}),
        output_schema=normalize_json_schema(dict(output_schema) if isinstance(output_schema, Mapping) else {}),
        metadata={
            "title": title,
            "annotations": dict(annotations),
            "server": dict(server_info),
            "command": list(command),
            "tool_index": index,
        },
    )


def _server_info(initialize_result: Mapping[str, Any]) -> Mapping[str, Any]:
    info = initialize_result.get("serverInfo")
    return dict(info) if isinstance(info, Mapping) else {}


def _command_name(command: Sequence[str]) -> str:
    if not command:
        return "unknown"
    return Path(command[0]).name or command[0]


def _stop_process(state: _ProcessState) -> None:
    process = state.process
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _process_exited_message(state: _ProcessState) -> str:
    stderr = "\n".join(state.stderr_lines[-10:])
    suffix = f" Stderr:\n{stderr}" if stderr else ""
    return f"MCP server exited with code {state.process.poll()}.{suffix}"


def _string_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)
