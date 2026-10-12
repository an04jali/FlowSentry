from __future__ import annotations

import importlib.metadata
import inspect
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from ..config import AgentToolDriftConfig
from .base import ToolAdapter
from .langchain_static import LangChainStaticAdapter
from .manifest import ManifestAdapter
from .mcp_stdio import McpStdioAdapter
from .openai_agents_static import OpenAIAgentsStaticAdapter
from .openapi import OpenAPIAdapter
from .python_static import PythonStaticAdapter


ENTRY_POINT_GROUP = "agent_tool_drift.adapters"


@dataclass(frozen=True)
class AdapterStatus:
    name: str
    source: str
    enabled: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "enabled": self.enabled,
            "reason": self.reason,
        }


def default_adapters(config: AgentToolDriftConfig) -> list[ToolAdapter]:
    adapters, _errors = resolve_adapters(config)
    return adapters


def resolve_adapters(config: AgentToolDriftConfig) -> tuple[list[ToolAdapter], list[dict[str, str]]]:
    adapters = builtin_adapters(config)
    external, errors = load_external_adapters(config)
    return adapters + external, errors


def builtin_adapters(config: AgentToolDriftConfig) -> list[ToolAdapter]:
    adapters: list[ToolAdapter] = []
    if config.python.enabled:
        adapters.append(PythonStaticAdapter())
    if config.manifests.enabled:
        adapters.append(ManifestAdapter())
    if config.openapi.enabled:
        adapters.append(OpenAPIAdapter())
    if config.mcp.servers:
        adapters.append(McpStdioAdapter())
    if config.langchain.enabled:
        adapters.append(LangChainStaticAdapter())
    if config.openai_agents.enabled:
        adapters.append(OpenAIAgentsStaticAdapter())
    return adapters


def adapter_status(config: AgentToolDriftConfig) -> list[AdapterStatus]:
    statuses = [
        AdapterStatus("python-static", "builtin", config.python.enabled, _enabled_reason(config.python.enabled)),
        AdapterStatus("manifest", "builtin", config.manifests.enabled, _enabled_reason(config.manifests.enabled)),
        AdapterStatus("openapi", "builtin", config.openapi.enabled, _enabled_reason(config.openapi.enabled)),
        AdapterStatus("mcp-stdio", "builtin", bool(config.mcp.servers), "enabled when mcp.servers is non-empty"),
        AdapterStatus("langchain-static", "builtin", config.langchain.enabled, _enabled_reason(config.langchain.enabled)),
        AdapterStatus(
            "openai-agents-static",
            "builtin",
            config.openai_agents.enabled,
            _enabled_reason(config.openai_agents.enabled),
        ),
    ]
    for entry_point in _adapter_entry_points():
        enabled, reason = _entry_point_enabled(entry_point.name, config)
        statuses.append(AdapterStatus(entry_point.name, ENTRY_POINT_GROUP, enabled, reason))
    return statuses


def load_external_adapters(config: AgentToolDriftConfig) -> tuple[list[ToolAdapter], list[dict[str, str]]]:
    adapters: list[ToolAdapter] = []
    errors: list[dict[str, str]] = []
    if not config.plugins.enabled:
        return adapters, errors

    for entry_point in _adapter_entry_points():
        enabled, reason = _entry_point_enabled(entry_point.name, config)
        if not enabled:
            continue
        try:
            loaded = entry_point.load()
            adapter = _coerce_adapter(loaded)
            adapters.append(adapter)
        except Exception as exc:
            errors.append({"adapter": entry_point.name, "error": str(exc), "reason": reason})
    return adapters, errors


def _coerce_adapter(value: Any) -> ToolAdapter:
    if isinstance(value, ToolAdapter):
        return value
    if inspect.isclass(value) and issubclass(value, ToolAdapter):
        return value()
    if callable(value):
        produced = value()
        if isinstance(produced, ToolAdapter):
            return produced
    raise TypeError("Adapter entry point must be a ToolAdapter instance, subclass, or zero-argument factory.")


def _adapter_entry_points() -> list[Any]:
    entry_points = importlib.metadata.entry_points()
    if hasattr(entry_points, "select"):
        return list(entry_points.select(group=ENTRY_POINT_GROUP))
    return list(entry_points.get(ENTRY_POINT_GROUP, []))


def _entry_point_enabled(name: str, config: AgentToolDriftConfig) -> tuple[bool, str]:
    if not config.plugins.enabled:
        return False, "plugins.enabled is false"
    if name in config.plugins.exclude:
        return False, "listed in plugins.exclude"
    if config.plugins.include and name not in config.plugins.include:
        return False, "not listed in plugins.include"
    return True, "enabled"


def _enabled_reason(enabled: bool) -> str:
    return "enabled by config" if enabled else "disabled by config"
