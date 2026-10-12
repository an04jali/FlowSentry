from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from ..config import AgentToolDriftConfig, McpServerConfig
from ..mcp_client import McpSnapshotOptions, snapshot_from_mcp_stdio
from ..models import Snapshot, ToolContract
from .base import AdapterContext, ToolAdapter


class McpStdioAdapter(ToolAdapter):
    name = "mcp-stdio"

    def scan(self, context: AdapterContext) -> list[ToolContract]:
        snapshot = snapshot_configured_mcp_servers(context.config, context.root)
        return snapshot.tools


def snapshot_configured_mcp_servers(
    config: AgentToolDriftConfig,
    root: Path,
    server_names: Optional[Iterable[str]] = None,
) -> Snapshot:
    requested = set(server_names) if server_names else None
    tools: list[ToolContract] = []
    environment = {"mcp": {"servers": {}}}

    for name, server in config.mcp.servers.items():
        if requested is not None and name not in requested:
            continue
        snapshot = snapshot_one_mcp_server(name, server, root)
        tools.extend(snapshot.tools)
        environment["mcp"]["servers"][name] = snapshot.environment.get("mcp", {})

    names = sorted(requested or config.mcp.servers.keys())
    return Snapshot(root=f"mcp://stdio/{','.join(names)}", tools=tools, environment=environment)


def snapshot_one_mcp_server(name: str, server: McpServerConfig, root: Path) -> Snapshot:
    cwd = Path(server.cwd) if server.cwd else root
    if not cwd.is_absolute():
        cwd = root / cwd
    return snapshot_from_mcp_stdio(
        McpSnapshotOptions(
            command=server.command,
            cwd=cwd,
            timeout=server.timeout,
            protocol_version=server.protocol_version,
            server_name=name,
        )
    )
