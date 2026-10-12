# agent-tool-drift

[English](README.md) | [Simplified Chinese](README.zh-CN.md)

`agent-tool-drift` is a configurable adapter framework for detecting when an
agent's tool contracts drift away from source code, manifests, OpenAPI specs,
MCP servers, framework-specific tool definitions, or dependency updates.

## Core Idea

The core function is **agent tool contract drift detection**.

The project turns tool definitions from different sources into stable
`ToolContract` snapshots, then compares two snapshots to find breaking and
non-breaking drift.

```text
adapters -> ToolContract -> Snapshot -> DiffResult -> reports / CI signals
```

- **Adapters** read Python decorators, manifests, OpenAPI specs, MCP servers,
  LangChain tools, OpenAI Agents SDK tools, or third-party plugin sources.
- **ToolContract** normalizes every discovered tool into the same shape:
  name, kind, source location, version, description, input schema, output schema,
  and metadata.
- **Snapshot** stores all contracts from a project or runtime source.
- **DiffResult** classifies changes as `BREAKING`, `WARNING`, or `INFO`.
- **Reports** turn the result into JSON, Markdown, HTML, SARIF, or GitHub
  Actions annotations.

It can:

- scan Python functions decorated as tools;
- scan JSON/YAML tool manifests, including OpenAI-style function tools and
  MCP-style `inputSchema` entries;
- scan JSON/YAML OpenAPI and Swagger operation contracts;
- launch MCP stdio servers and snapshot their advertised tools;
- statically detect LangChain tools when enabled;
- statically detect OpenAI Agents SDK `@function_tool` definitions when enabled;
- load third-party scanner adapters through Python entry points when enabled;
- generate reproducible snapshots;
- compare snapshots and classify drift;
- infer likely input and schema property rename candidates without hiding the underlying removed/added changes;
- attach practical migration advice to each detected change;
- attach confidence and evidence to deterministic and inferred changes;
- compute a deterministic compatibility score and risk level for each diff;
- produce JSON, Markdown, HTML, SARIF, and GitHub annotation reports.

## Install

```bash
pip install -e ".[dev]"
```

For normal package use:

```bash
pip install .
```

## Quick Start

Create a config file:

```bash
agent-tool-drift init
```

Create a snapshot:

```bash
agent-tool-drift snapshot examples/python_agent --config agent-tool-drift.yaml -o snapshot.json
```

Try YAML manifest and OpenAPI scanning:

```bash
agent-tool-drift snapshot examples/yaml_agent --format markdown
```

Try LangChain static scanning:

```bash
agent-tool-drift snapshot examples/langchain_agent --format markdown
```

Try OpenAI Agents SDK static scanning:

```bash
agent-tool-drift snapshot examples/openai_agents_agent --format markdown
```

Compare two snapshots:

```bash
agent-tool-drift diff snapshot-old.json snapshot-new.json --format markdown
```

Create an HTML report:

```bash
agent-tool-drift diff snapshot-old.json snapshot-new.json --format html -o report.html
```

Snapshot a running MCP stdio server:

```bash
agent-tool-drift mcp-snapshot -o mcp-tools.json -- python examples/mcp_server/mock_server.py
```

Use a baseline in CI:

```bash
agent-tool-drift check . --baseline .agent-tool-drift/snapshot.json --fail-on-breaking
```

If the baseline does not exist, `check` creates it and exits successfully.
When `--baseline` is omitted, `check <path>` uses
`<path>/.agent-tool-drift/snapshot.json`.
When an intentional tool change is accepted, refresh the baseline:

```bash
agent-tool-drift check . --baseline .agent-tool-drift/snapshot.json --update-baseline
```

Generate SARIF and GitHub annotations:

```bash
agent-tool-drift diff old.json new.json --format sarif -o agent-tool-drift.sarif --github-annotations
```

## Configuration

`agent-tool-drift` auto-discovers these files in the project root:

- `agent-tool-drift.yaml`
- `agent-tool-drift.yml`
- `.agent-tool-drift.yaml`
- `.agent-tool-drift.yml`
- `.agent-tool-drift/config.yaml`
- `.agent-tool-drift/config.yml`
- `agent-tool-drift.json`

Example:

```yaml
python:
  decorators:
    - tool
    - function_tool
    - my_agent.register_tool

manifests:
  include:
    - "tools.json"
    - "config/**/*.tools.yaml"

openapi:
  include:
    - "openapi.yaml"
    - "specs/**/*.json"

mcp:
  servers:
    filesystem:
      command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "."]
      cwd: "."
      timeout: 10
      protocol_version: "2025-06-18"

langchain:
  enabled: true
  include:
    - "**/*.py"

openai_agents:
  enabled: true
  include:
    - "**/*.py"

plugins:
  enabled: false
  include: []
  exclude: []

policy:
  fail_on:
    - compatibility:breaking
    # You can also use exact change codes or semantic selectors:
    # - input.required_added
    # - severity:BREAKING
    # - domain:input
    # - direction:output
  ignore:
    - tool.description_changed

advice:
  agent_guidance: "Inspect project-specific agents, callers, and tests before editing."
  overrides:
    input.required_added:
      suggestion: "Project rule: ship new arguments as optional first, then tighten later."
      kind: "project"
      category: "input"
```

Policy is applied by `diff` and `check` when you pass `--config`. Use
`--fail-on-policy` to fail CI on configured selectors. The default selector,
`compatibility:breaking`, avoids false failures for direction-sensitive schema
changes, such as output constraints becoming narrower. `policy.ignore` accepts
the same selector forms. Semantic selectors such as `severity:breaking`,
`domain:input`, and `direction:output` are case-insensitive.

Inspect the active scanner setup:

```bash
agent-tool-drift adapters . --config agent-tool-drift.yaml
agent-tool-drift doctor . --config agent-tool-drift.yaml
```

## Adapter Framework

The scanner is organized around small adapters:

```text
src/agent_tool_drift/adapters/
  base.py                 # AdapterContext and ToolAdapter interface
  python_static.py        # AST-based Python decorator scanner
  manifest.py             # JSON/YAML tool manifests
  openapi.py              # JSON/YAML OpenAPI and Swagger specs
  mcp_stdio.py            # Configured MCP stdio servers
  langchain_static.py     # LangChain @tool and StructuredTool.from_function
  openai_agents_static.py # OpenAI Agents SDK @function_tool
  registry.py             # Built-in and external adapter loading
```

All adapters emit the same `ToolContract` model, so new ecosystems can be added
without changing diffing, reporting, or CI behavior.

## External Adapter Plugins

Third-party packages can expose adapters through the
`agent_tool_drift.adapters` Python entry point group:

```toml
[project.entry-points."agent_tool_drift.adapters"]
my-framework = "my_package.tool_drift:MyFrameworkAdapter"
```

The object can be a `ToolAdapter` subclass, a `ToolAdapter` instance, or a
zero-argument factory returning a `ToolAdapter`. External plugins are disabled
by default; enable them explicitly:

```yaml
plugins:
  enabled: true
  include:
    - my-framework
```

## Python Tool Detection

The generic Python scanner uses `ast`, so it does not import project code. It
recognizes common decorator names such as:

- `@tool`
- `@agent_tool`
- `@function_tool`
- `@mcp.tool`
- `@server.tool`

```python
from some_agent_framework import tool

@tool(name="search_web", description="Search web pages")
def search_web(query: str, top_k: int = 5) -> list[dict]:
    """Search web pages."""
    return []
```

Common type hints such as `Optional`, `Union`, `Literal`, `Annotated`, `list[T]`,
and `dict[str, T]` are converted into approximate JSON Schema.

## OpenAI Agents SDK Detection

OpenAI Agents SDK scanning is disabled by default to avoid duplicate results
with the generic Python decorator scanner. Enable it when you want
framework-specific metadata:

```yaml
python:
  enabled: false
openai_agents:
  enabled: true
```

The static adapter recognizes `@function_tool` from the OpenAI Agents SDK:

```python
from agents import RunContextWrapper, function_tool

@function_tool(
    name_override="weather_lookup",
    description_override="Get current weather for a city.",
)
def get_weather(city: str, units: str = "metric") -> dict:
    """Return weather data for a city."""
    return {"city": city, "units": units}

@function_tool(defer_loading=True)
async def lookup_user(ctx: RunContextWrapper, user_id: str) -> str:
    """Look up an internal user profile."""
    return user_id
```

The adapter reads the function signature, return annotation, docstring, and
known `function_tool(...)` options such as `name_override`,
`description_override`, `use_docstring_info`, and `defer_loading`. It hides the
first `RunContextWrapper`/`ctx` argument from the generated input schema because
that parameter is runtime context, not model input.

Reference: [OpenAI Agents SDK tools documentation](https://openai.github.io/openai-agents-python/tools/).

## JSON Manifest Detection

The scanner reads files named:

- `agent-tools.json`
- `agent-tools.yaml`
- `agent-tools.yml`
- `tools.json`
- `tools.yaml`
- `tools.yml`
- `tool_definitions.json`
- `tool_definitions.yaml`
- `tool_definitions.yml`
- `mcp-tools.json`
- `mcp-tools.yaml`
- `mcp-tools.yml`

Supported shapes include:

```json
{
  "tools": [
    {
      "name": "search_web",
      "description": "Search web pages",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string"}
        },
        "required": ["query"]
      }
    }
  ]
}
```

OpenAI-style function tool manifests are also supported:

```json
[
  {
    "type": "function",
    "function": {
      "name": "search_web",
      "description": "Search web pages",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string"}
        },
        "required": ["query"]
      }
    }
  }
]
```

## OpenAPI Detection

The scanner reads:

- `openapi.json`
- `openapi.yaml`
- `openapi.yml`
- `swagger.json`
- `swagger.yaml`
- `swagger.yml`

Each operation becomes one tool. `operationId` is used as the tool name when
available; otherwise the scanner derives a name from the HTTP method and path.
Local `$ref` entries are resolved for parameters, request bodies, responses, and
nested schemas under the same document.

Path-level and operation-level parameters are merged using OpenAPI override
semantics. The scanner prefers JSON-like content types, including vendor media
types such as `application/vnd.api+json`, and recognizes quoted or unquoted 2xx
success response statuses.
When parameters from different locations share the same name, the scanner
disambiguates them with location prefixes such as `path_id` and `query_id`.
If a parameter already occupies `body`, the request body is exposed as
`request_body`.

## LangChain Detection

LangChain scanning is disabled by default to avoid duplicate results with the
generic Python decorator scanner. Enable it when you want framework-specific
metadata:

```yaml
python:
  enabled: false
langchain:
  enabled: true
```

The static adapter recognizes common patterns:

```python
from langchain.tools import tool
from langchain_core.tools import StructuredTool

@tool("customer_search", description="Search customer records.")
def search_customers(query: str, limit: int = 10) -> dict:
    """Search customer records."""
    return {}

ticket_summary_tool = StructuredTool.from_function(
    func=search_customers,
    name="ticket_summary",
)
```

The adapter hides LangChain-injected arguments named `runtime` and `config` from
the generated input schema.

## MCP Stdio Detection

`mcp-snapshot` launches a command as an MCP stdio server, sends the standard
JSON-RPC initialization handshake, calls `tools/list`, follows `nextCursor`
pagination, and emits the same snapshot format as file-based scanning.

```bash
agent-tool-drift mcp-snapshot --server-name filesystem -o filesystem-tools.json -- npx -y @modelcontextprotocol/server-filesystem .
```

Configured MCP servers can also be placed in `agent-tool-drift.yaml` and run by
name:

```bash
agent-tool-drift mcp-snapshot --config agent-tool-drift.yaml --server filesystem
```

## What Counts As Drift?

The diff engine flags changes such as:

- added required input fields;
- removed input fields;
- likely input rename candidates;
- changed input types;
- changed output types;
- changed defaults;
- narrowed or relaxed numeric, string, array, and object constraints;
- changed nullability;
- changed `additionalProperties` behavior;
- changed array `items` schemas;
- changed `oneOf`, `anyOf`, or `allOf` composition;
- changed nested object `required` fields;
- likely schema property rename candidates;
- removed tools;
- description changes;
- source path changes;
- dependency/package version changes when present in the snapshot.

This project is intentionally conservative: anything likely to break an agent's
tool invocation is treated as `BREAKING`.

Each diff summary includes a deterministic compatibility score:

- `compatibility_score`: starts at `100` and subtracts penalties for each drift.
  Breaking changes receive the full penalty; uncertain changes receive a
  reduced penalty; backward-compatible changes receive only a small review
  penalty.
- `risk_level`: `low`, `medium`, `high`, or `critical`.

The score is intentionally simple and stable enough for CI. It is a triage
signal, not a formal proof of runtime safety.

Each change also includes:

- `domain`: `tool`, `input`, `schema`, `environment`, or `unknown`;
- `operation`: normalized operation such as `added`, `removed`, `changed`,
  `narrowed`, `widened`, or `rename_candidate`;
- `direction`: `input`, `output`, `tool`, `environment`, or `bidirectional`;
- `compatibility`: `breaking`, `backward_compatible`, `uncertain`, or
  `unknown`;
- `confidence`: `1.0` for direct deterministic checks, lower for inferred
  root-cause matches such as likely renames;
- `evidence`: a short machine-readable explanation, for example name similarity
  and schema similarity for a rename inference.

Rename candidates are intentionally reported as extra diagnostics. They do not
replace the underlying removed/added changes, because the scanner cannot prove a
rename without project context.

Every `ContractChange` also includes an `advice` field. The advice is not magic
and does not rewrite your code; it gives the reviewer the usual safe migration
path, such as keeping a compatibility wrapper for a removed tool, making a new
input optional during rollout, or checking downstream parsers before removing an
output property.

Advice is deliberately marked as heuristic. JSON and SARIF reports include:

- `advice`: the default migration suggestion;
- `advice_kind`: currently `heuristic`;
- `advice_category`: `tool`, `input`, `schema`, `environment`, or `unknown`;
- `agent_guidance`: a reminder that a real migration model should inspect the
  source code, callers, tests, and product context, then apply, adapt, or ignore
  the suggestion.

The built-in rules live in `src/agent_tool_drift/advice.py`. They are stable and
reproducible for CI, but they are not meant to replace human or agent judgment.
Teams can override advice in config with `advice.overrides`. Override values can
be plain strings or objects with `suggestion`, `kind`, `category`, and
`agent_guidance`.

## CI

This repository includes a GitHub Actions workflow in
`.github/workflows/ci.yml`. It installs the package, runs tests on Python
3.9-3.12, and performs CLI smoke tests.

## GitHub Action

This repository also exposes a composite GitHub Action through `action.yml`.
Use it after checking out your repository:

```yaml
name: Agent Tool Drift

on:
  pull_request:
  push:
    branches: ["main"]

jobs:
  tool-drift:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v4
      - uses: fykong/agent-tool-drift@v1
        with:
          path: "."
          config: "agent-tool-drift.yaml"
          baseline: ".agent-tool-drift/snapshot.json"
          report-format: "sarif"
          report-path: "agent-tool-drift.sarif"
          fail-on-policy: "true"
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: agent-tool-drift.sarif
```

The action emits GitHub annotations by default. SARIF upload is kept as a
separate explicit step so repositories can choose whether to enable Code
Scanning.

## Diagnostics

Use `adapters` to see which scanners are available and enabled:

```bash
agent-tool-drift adapters . --format markdown
```

Use `doctor` to load config, scan the project, and summarize tool counts by kind
and adapter:

```bash
agent-tool-drift doctor . --config agent-tool-drift.yaml --format json
```

## Skill Wrapper

`skills/codex-tool-drift/SKILL.md` is a thin Codex skill wrapper. It teaches an
agent how to run the CLI and interpret reports, while keeping the actual logic in
normal, testable code.

## Current Limitations

- Python type extraction is intentionally approximate.
- Static Python scanning does not import code. Dynamic runtime-generated tools
  should be exposed through MCP or a future framework-specific runtime adapter.
- OpenAPI `$ref` resolution currently supports local refs in the same document.
- The OpenAI Agents SDK adapter detects function tools statically; it does not
  execute `Agent(...)` construction logic.
