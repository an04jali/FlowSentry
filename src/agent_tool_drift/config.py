from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

import yaml


CONFIG_FILENAMES = (
    "agent-tool-drift.yaml",
    "agent-tool-drift.yml",
    ".agent-tool-drift.yaml",
    ".agent-tool-drift.yml",
    ".agent-tool-drift/config.yaml",
    ".agent-tool-drift/config.yml",
    "agent-tool-drift.json",
)

DEFAULT_CONFIG_TEXT = """# agent-tool-drift configuration
python:
  enabled: true
  include:
    - "**/*.py"
  exclude:
    - ".git/**"
    - ".venv/**"
    - "venv/**"
    - "env/**"
    - "node_modules/**"
    - "site-packages/**"
    - "build/**"
    - "dist/**"
  decorators:
    - tool
    - agent_tool
    - function_tool
    - mcp_tool
    - openai_tool
    - structured_tool

manifests:
  enabled: true
  include:
    - "agent-tools.json"
    - "agent-tools.yaml"
    - "agent-tools.yml"
    - "tools.json"
    - "tools.yaml"
    - "tools.yml"
    - "tool_definitions.json"
    - "tool_definitions.yaml"
    - "tool_definitions.yml"
    - "mcp-tools.json"
    - "mcp-tools.yaml"
    - "mcp-tools.yml"

openapi:
  enabled: true
  include:
    - "openapi.json"
    - "openapi.yaml"
    - "openapi.yml"
    - "swagger.json"
    - "swagger.yaml"
    - "swagger.yml"

mcp:
  servers: {}
  # Example:
  # servers:
  #   filesystem:
  #     command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]
  #     cwd: "."
  #     timeout: 10
  #     protocol_version: "2025-06-18"

policy:
  fail_on:
    - compatibility:breaking
  ignore: []

advice:
  agent_guidance: ""
  overrides: {}

langchain:
  enabled: false
  include:
    - "**/*.py"
  exclude:
    - ".git/**"
    - ".venv/**"
    - "venv/**"
    - "env/**"
    - "node_modules/**"
    - "site-packages/**"
    - "build/**"
    - "dist/**"

openai_agents:
  enabled: false
  include:
    - "**/*.py"
  exclude:
    - ".git/**"
    - ".venv/**"
    - "venv/**"
    - "env/**"
    - "node_modules/**"
    - "site-packages/**"
    - "build/**"
    - "dist/**"

plugins:
  enabled: false
  include: []
  exclude: []
"""


@dataclass(frozen=True)
class PythonConfig:
    enabled: bool = True
    include: Tuple[str, ...] = ("**/*.py",)
    exclude: Tuple[str, ...] = (
        ".git/**",
        ".venv/**",
        "venv/**",
        "env/**",
        "node_modules/**",
        "site-packages/**",
        "build/**",
        "dist/**",
    )
    decorators: Tuple[str, ...] = (
        "tool",
        "agent_tool",
        "function_tool",
        "mcp_tool",
        "openai_tool",
        "structured_tool",
    )



@dataclass(frozen=True)
class FilePatternConfig:
    enabled: bool = True
    include: Tuple[str, ...] = ()
    exclude: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowConfig:
    """Tools and regression tests associated with a workflow."""
    tools: Tuple[str, ...] = ()
    regression_tests: Tuple[str, ...] = ()


@dataclass(frozen=True)
class McpServerConfig:
    command: Tuple[str, ...]
    cwd: Optional[str] = None
    timeout: float = 10.0
    protocol_version: str = "2025-06-18"


@dataclass(frozen=True)
class McpConfig:
    servers: Mapping[str, McpServerConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class LangChainConfig:
    enabled: bool = False
    include: Tuple[str, ...] = ("**/*.py",)
    exclude: Tuple[str, ...] = (
        ".git/**",
        ".venv/**",
        "venv/**",
        "env/**",
        "node_modules/**",
        "site-packages/**",
        "build/**",
        "dist/**",
    )


@dataclass(frozen=True)
class OpenAIAgentsConfig:
    enabled: bool = False
    include: Tuple[str, ...] = ("**/*.py",)
    exclude: Tuple[str, ...] = (
        ".git/**",
        ".venv/**",
        "venv/**",
        "env/**",
        "node_modules/**",
        "site-packages/**",
        "build/**",
        "dist/**",
    )


@dataclass(frozen=True)
class PolicyConfig:
    fail_on: Tuple[str, ...] = ("compatibility:breaking",)
    ignore: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AdviceOverrideConfig:
    suggestion: Optional[str] = None
    kind: Optional[str] = None
    category: Optional[str] = None
    agent_guidance: Optional[str] = None


@dataclass(frozen=True)
class AdviceConfig:
    agent_guidance: Optional[str] = None
    overrides: Mapping[str, AdviceOverrideConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginsConfig:
    enabled: bool = False
    include: Tuple[str, ...] = ()
    exclude: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentToolDriftConfig:
    python: PythonConfig = field(default_factory=PythonConfig)
    manifests: FilePatternConfig = field(
        default_factory=lambda: FilePatternConfig(
            include=(
                "agent-tools.json",
                "agent-tools.yaml",
                "agent-tools.yml",
                "tools.json",
                "tools.yaml",
                "tools.yml",
                "tool_definitions.json",
                "tool_definitions.yaml",
                "tool_definitions.yml",
                "mcp-tools.json",
                "mcp-tools.yaml",
                "mcp-tools.yml",
            )
        )
    )
    openapi: FilePatternConfig = field(
        default_factory=lambda: FilePatternConfig(
            include=(
                "openapi.json",
                "openapi.yaml",
                "openapi.yml",
                "swagger.json",
                "swagger.yaml",
                "swagger.yml",
            )
        )
    )
    mcp: McpConfig = field(default_factory=McpConfig)
    langchain: LangChainConfig = field(default_factory=LangChainConfig)
    openai_agents: OpenAIAgentsConfig = field(default_factory=OpenAIAgentsConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    advice: AdviceConfig = field(default_factory=AdviceConfig)
    workflows: Mapping[str, WorkflowConfig] = field(default_factory=dict)
    source_path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "python": {
                "enabled": self.python.enabled,
                "include": list(self.python.include),
                "exclude": list(self.python.exclude),
                "decorators": list(self.python.decorators),
            },
            "manifests": {
                "enabled": self.manifests.enabled,
                "include": list(self.manifests.include),
                "exclude": list(self.manifests.exclude),
            },
            "openapi": {
                "enabled": self.openapi.enabled,
                "include": list(self.openapi.include),
                "exclude": list(self.openapi.exclude),
            },
            "mcp": {
                "servers": {
                    name: {
                        "command": list(server.command),
                        "cwd": server.cwd,
                        "timeout": server.timeout,
                        "protocol_version": server.protocol_version,
                    }
                    for name, server in self.mcp.servers.items()
                }
            },
            "langchain": {
                "enabled": self.langchain.enabled,
                "include": list(self.langchain.include),
                "exclude": list(self.langchain.exclude),
            },
            "openai_agents": {
                "enabled": self.openai_agents.enabled,
                "include": list(self.openai_agents.include),
                "exclude": list(self.openai_agents.exclude),
            },
            "policy": {
                "fail_on": list(self.policy.fail_on),
                "ignore": list(self.policy.ignore),
            },
            "advice": {
                "agent_guidance": self.advice.agent_guidance,
                "overrides": {
                    code: {
                        "suggestion": override.suggestion,
                        "kind": override.kind,
                        "category": override.category,
                        "agent_guidance": override.agent_guidance,
                    }
                    for code, override in self.advice.overrides.items()
                },
            },
            "plugins": {
                "enabled": self.plugins.enabled,
                "include": list(self.plugins.include),
                "exclude": list(self.plugins.exclude),
            },
            "workflows": {
                name: {
                    "tools": list(workflow.tools),
                    "regression_tests": list(workflow.regression_tests),
                }
                for name, workflow in self.workflows.items()
            },
            "source_path": str(self.source_path) if self.source_path else None,
        }


def default_config() -> AgentToolDriftConfig:
    return AgentToolDriftConfig()


def find_config_path(root: Union[Path, str]) -> Optional[Path]:
    root_path = Path(root).resolve()
    for name in CONFIG_FILENAMES:
        candidate = root_path / name
        if candidate.exists():
            return candidate
    return None


def load_config(path: Optional[Union[Path, str]] = None, root: Union[Path, str] = ".") -> AgentToolDriftConfig:
    resolved = _resolve_config_path(path, root) if path else find_config_path(root)
    if resolved is None:
        return default_config()
    data = _read_config_document(resolved)
    if not isinstance(data, Mapping):
        raise ValueError(f"Configuration file must contain an object: {resolved}")
    return parse_config(data, source_path=resolved)


def _resolve_config_path(path: Union[Path, str], root: Union[Path, str]) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate.resolve()
    root_candidate = Path(root).resolve() / candidate
    if root_candidate.exists():
        return root_candidate.resolve()
    if candidate.exists():
        return candidate.resolve()
    return candidate.resolve()


def parse_config(data: Mapping[str, Any], source_path: Optional[Path] = None) -> AgentToolDriftConfig:
    base = default_config()
    python_data = _mapping(data.get("python"))
    manifests_data = _mapping(data.get("manifests"))
    openapi_data = _mapping(data.get("openapi"))
    mcp_data = _mapping(data.get("mcp"))
    langchain_data = _mapping(data.get("langchain"))
    openai_agents_data = _mapping(data.get("openai_agents"))
    plugins_data = _mapping(data.get("plugins"))
    policy_data = _mapping(data.get("policy"))
    advice_data = _mapping(data.get("advice"))
    workflows = _parse_workflows(data.get("workflows"))

    return AgentToolDriftConfig(
        python=PythonConfig(
            enabled=_bool(python_data.get("enabled"), base.python.enabled),
            include=_strings(python_data.get("include"), base.python.include),
            exclude=_strings(python_data.get("exclude"), base.python.exclude),
            decorators=_strings(python_data.get("decorators"), base.python.decorators),
        ),
        manifests=FilePatternConfig(
            enabled=_bool(manifests_data.get("enabled"), base.manifests.enabled),
            include=_strings(manifests_data.get("include"), base.manifests.include),
            exclude=_strings(manifests_data.get("exclude"), base.manifests.exclude),
        ),
        openapi=FilePatternConfig(
            enabled=_bool(openapi_data.get("enabled"), base.openapi.enabled),
            include=_strings(openapi_data.get("include"), base.openapi.include),
            exclude=_strings(openapi_data.get("exclude"), base.openapi.exclude),
        ),
        mcp=McpConfig(servers=_parse_mcp_servers(mcp_data.get("servers"))),
        langchain=LangChainConfig(
            enabled=_bool(langchain_data.get("enabled"), base.langchain.enabled),
            include=_strings(langchain_data.get("include"), base.langchain.include),
            exclude=_strings(langchain_data.get("exclude"), base.langchain.exclude),
        ),
        openai_agents=OpenAIAgentsConfig(
            enabled=_bool(openai_agents_data.get("enabled"), base.openai_agents.enabled),
            include=_strings(openai_agents_data.get("include"), base.openai_agents.include),
            exclude=_strings(openai_agents_data.get("exclude"), base.openai_agents.exclude),
        ),
        plugins=PluginsConfig(
            enabled=_bool(plugins_data.get("enabled"), base.plugins.enabled),
            include=_strings(plugins_data.get("include"), base.plugins.include),
            exclude=_strings(plugins_data.get("exclude"), base.plugins.exclude),
        ),
        policy=PolicyConfig(
            fail_on=_strings(policy_data.get("fail_on"), base.policy.fail_on),
            ignore=_strings(policy_data.get("ignore"), base.policy.ignore),
        ),
        advice=AdviceConfig(
            agent_guidance=_optional_string(advice_data.get("agent_guidance")),
            overrides=_parse_advice_overrides(advice_data.get("overrides")),
        ),
        workflows=workflows,
        source_path=source_path,
    )


def write_default_config(path: Union[Path, str], force: bool = False) -> Path:
    output = Path(path)
    if output.exists() and not force:
        raise FileExistsError(f"Configuration file already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return output


def _read_config_document(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            if path.suffix == ".json":
                return json.load(handle)
            return yaml.safe_load(handle)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Failed to parse configuration file {path}: {exc}") from exc


def _parse_workflows(value: Any) -> Mapping[str, WorkflowConfig]:
    """Parse workflow-to-tool and regression-test mappings."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("Configuration field 'workflows' must be an object.")

    workflows: Dict[str, WorkflowConfig] = {}
    for raw_name, raw_workflow in value.items():
        name = str(raw_name).strip()
        field_prefix = f"workflows.{name}"

        if not name:
            raise ValueError("Workflow names in 'workflows' must not be empty.")
        if not isinstance(raw_workflow, Mapping):
            raise ValueError(
                f"Configuration field '{field_prefix}' must be an object."
            )

        tools = _workflow_string_list(
            raw_workflow.get("tools", []),
            field=f"{field_prefix}.tools",
        )
        regression_tests = _workflow_string_list(
            raw_workflow.get("regression_tests", []),
            field=f"{field_prefix}.regression_tests",
        )

        workflows[name] = WorkflowConfig(
            tools=tools,
            regression_tests=regression_tests,
        )

    return workflows


def _workflow_string_list(value: Any, field: str) -> Tuple[str, ...]:
    """Require a list/tuple of non-empty strings for workflow fields."""
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(
            f"Configuration field '{field}' must be a list of strings."
        )

    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"Configuration field '{field}' must contain only non-empty strings."
            )
        result.append(item.strip())
    return tuple(result)


def _parse_mcp_servers(value: Any) -> Mapping[str, McpServerConfig]:
    if not isinstance(value, Mapping):
        return {}
    servers: Dict[str, McpServerConfig] = {}
    for name, raw in value.items():
        if not isinstance(raw, Mapping):
            continue
        command = _strings(raw.get("command"), ())
        if not command:
            continue
        servers[str(name)] = McpServerConfig(
            command=command,
            cwd=str(raw["cwd"]) if raw.get("cwd") is not None else None,
            timeout=_float(raw.get("timeout"), 10.0, field=f"mcp.servers.{name}.timeout"),
            protocol_version=str(raw.get("protocol_version", "2025-06-18")),
        )
    return servers


def _parse_advice_overrides(value: Any) -> Mapping[str, AdviceOverrideConfig]:
    if not isinstance(value, Mapping):
        return {}
    overrides: Dict[str, AdviceOverrideConfig] = {}
    for code, raw in value.items():
        if isinstance(raw, str):
            overrides[str(code)] = AdviceOverrideConfig(suggestion=raw)
        elif isinstance(raw, Mapping):
            overrides[str(code)] = AdviceOverrideConfig(
                suggestion=_optional_string(raw.get("suggestion") or raw.get("advice")),
                kind=_optional_string(raw.get("kind")),
                category=_optional_string(raw.get("category")),
                agent_guidance=_optional_string(raw.get("agent_guidance")),
            )
    return overrides


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _strings(value: Any, default: Iterable[str]) -> Tuple[str, ...]:
    if value is None:
        return tuple(default)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value)
    return tuple(default)


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _float(value: Any, default: float, field: str) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Configuration field '{field}' must be a number.") from exc


def _optional_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    return text or None
