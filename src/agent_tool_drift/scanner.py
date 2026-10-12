from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .adapters import AdapterContext, ToolAdapter, resolve_adapters
from .adapters.manifest import scan_manifest_tools as _scan_manifest_tools
from .adapters.openapi import scan_openapi_tools as _scan_openapi_tools
from .adapters.python_static import scan_python_tools as _scan_python_tools
from .config import AgentToolDriftConfig, default_config, load_config
from .models import Snapshot, ToolContract


def scan_project(
    root: Union[Path, str],
    config: Optional[AgentToolDriftConfig] = None,
    config_path: Optional[Union[Path, str]] = None,
    adapters: Optional[list[ToolAdapter]] = None,
) -> Snapshot:
    root_path = Path(root).resolve()
    resolved_config = config or load_config(config_path, root=root_path)
    adapter_load_errors: list[dict[str, Any]] = []
    if adapters is None:
        selected_adapters, adapter_load_errors = resolve_adapters(resolved_config)
    else:
        selected_adapters = adapters
    context = AdapterContext(root=root_path, config=resolved_config)

    tools: list[ToolContract] = []
    adapter_errors: list[dict[str, Any]] = list(adapter_load_errors)
    for adapter in selected_adapters:
        try:
            tools.extend(adapter.scan(context))
        except Exception as exc:  # pragma: no cover - defensive isolation for external adapters.
            adapter_errors.append({"adapter": adapter.name, "error": str(exc)})

    environment = _environment()
    environment["config"] = resolved_config.to_dict()
    if adapter_errors:
        environment["adapter_errors"] = adapter_errors
    return Snapshot(root=str(root_path), tools=tools, environment=environment)


def scan_python_tools(root: Union[Path, str]) -> list[ToolContract]:
    config = default_config()
    return _scan_python_tools(Path(root).resolve(), decorators=config.python.decorators)


def scan_manifest_tools(root: Union[Path, str]) -> list[ToolContract]:
    config = default_config()
    return _scan_manifest_tools(Path(root).resolve(), include=config.manifests.include, exclude=config.manifests.exclude)


def scan_openapi_tools(root: Union[Path, str]) -> list[ToolContract]:
    config = default_config()
    return _scan_openapi_tools(Path(root).resolve(), include=config.openapi.include, exclude=config.openapi.exclude)


def _environment() -> Dict[str, Any]:
    packages = {}
    for name in ("openai", "openai-agents", "langchain", "llama-index", "mcp"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {
        "python": sys.version.split()[0],
        "packages": packages,
    }
