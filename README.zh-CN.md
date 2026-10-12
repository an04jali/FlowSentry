# agent-tool-drift

[English](README.md) | [简体中文](README.zh-CN.md)

`agent-tool-drift` 是一个可配置、可扩展的 Agent 工具接口漂移检测框架。

它的目标很直接：**工具库或工具源码变了以后，提前发现 Agent 可能会坏在哪里。**

## 核心逻辑

项目会把不同来源的工具定义统一抽取成 `ToolContract`，保存为快照，然后比较新旧快照。

```text
adapters -> ToolContract -> Snapshot -> DiffResult -> reports / CI signals
```

- **Adapters**：扫描不同来源的工具，比如 Python decorator、JSON/YAML manifest、OpenAPI、MCP server、LangChain、OpenAI Agents SDK，或者第三方插件。
- **ToolContract**：统一后的工具接口说明，包括工具名、类型、源码位置、描述、输入 schema、输出 schema 和元数据。
- **Snapshot**：某一次扫描得到的工具接口快照。
- **DiffResult**：比较两份快照，判断变化是 `BREAKING`、`WARNING` 还是 `INFO`。
- **Reports**：输出 JSON、Markdown、HTML、SARIF 或 GitHub Actions annotations。

它不会自动修改你的 Agent 源码，也不会自动升级工具调用代码。它做的是更基础的事：

**告诉你工具接口到底变了什么，这些变化会不会破坏旧的 Agent 调用。**

## 能做什么

- 扫描 Python 中通过 decorator 定义的工具。
- 扫描 JSON/YAML 工具清单，包括 OpenAI-style function tools 和 MCP-style `inputSchema`。
- 扫描 OpenAPI / Swagger 文档。
- 启动 MCP stdio server，并读取运行时暴露的 `tools/list`。
- 可选扫描 LangChain 的 `@tool` 和 `StructuredTool.from_function(...)`。
- 可选扫描 OpenAI Agents SDK 的 `@function_tool`。
- 通过 Python entry point 加载第三方 adapter 插件。
- 生成可复现的工具接口快照。
- 比较新旧快照，识别 breaking drift。
- 推断可能的输入参数重命名候选和 schema 字段重命名候选，但不隐藏底层 removed/added 变化。
- 给每个变化附带可操作的迁移建议。
- 给每个变化附带 confidence 和 evidence。
- 给每次 diff 计算确定性的兼容性评分和风险等级。
- 输出 JSON、Markdown、HTML、SARIF 和 GitHub annotation。
- 作为 CLI、本地检查工具、CI 工具或 GitHub Action 使用。

## 安装

开发安装：

```bash
pip install -e ".[dev]"
```

普通安装：

```bash
pip install .
```

## 快速开始

创建配置文件：

```bash
agent-tool-drift init
```

生成工具快照：

```bash
agent-tool-drift snapshot examples/python_agent --config agent-tool-drift.yaml -o snapshot.json
```

扫描 YAML manifest 和 OpenAPI 示例：

```bash
agent-tool-drift snapshot examples/yaml_agent --format markdown
```

扫描 LangChain 示例：

```bash
agent-tool-drift snapshot examples/langchain_agent --format markdown
```

扫描 OpenAI Agents SDK 示例：

```bash
agent-tool-drift snapshot examples/openai_agents_agent --format markdown
```

比较两个快照：

```bash
agent-tool-drift diff snapshot-old.json snapshot-new.json --format markdown
```

生成 HTML 报告：

```bash
agent-tool-drift diff snapshot-old.json snapshot-new.json --format html -o report.html
```

扫描 MCP stdio server：

```bash
agent-tool-drift mcp-snapshot -o mcp-tools.json -- python examples/mcp_server/mock_server.py
```

在 CI 中使用 baseline：

```bash
agent-tool-drift check . --baseline .agent-tool-drift/snapshot.json --fail-on-breaking
```

如果 baseline 不存在，`check` 会自动创建 baseline 并正常退出。如果省略 `--baseline`，`check <path>` 会默认使用 `<path>/.agent-tool-drift/snapshot.json`。接受一次有意变更后，可以更新 baseline：

```bash
agent-tool-drift check . --baseline .agent-tool-drift/snapshot.json --update-baseline
```

## 配置

`agent-tool-drift` 会在项目根目录自动发现这些配置文件：

- `agent-tool-drift.yaml`
- `agent-tool-drift.yml`
- `.agent-tool-drift.yaml`
- `.agent-tool-drift.yml`
- `.agent-tool-drift/config.yaml`
- `.agent-tool-drift/config.yml`
- `agent-tool-drift.json`

示例配置：

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
    # 也可以使用精确 change code 或语义 selector：
    # - input.required_added
    # - severity:BREAKING
    # - domain:input
    # - direction:output
  ignore:
    - tool.description_changed

advice:
  agent_guidance: "修改前先检查本项目的 agents、调用方和测试。"
  overrides:
    input.required_added:
      suggestion: "项目规则：新增参数必须先以 optional 方式发布，后续版本再收紧。"
      kind: "project"
      category: "input"
```

`policy` 会在 `diff` 和 `check` 中生效。使用 `--fail-on-policy` 可以让 CI 按配置中的 `fail_on` selector 失败。默认的 `compatibility:breaking` 会避开一些方向敏感的误判，例如 output 约束变窄通常不应该直接让 CI 失败。`policy.ignore` 支持同一套 selector。`severity:breaking`、`domain:input`、`direction:output` 这类语义 selector 大小写不敏感。

查看当前 scanner 状态：

```bash
agent-tool-drift adapters . --config agent-tool-drift.yaml
agent-tool-drift doctor . --config agent-tool-drift.yaml
```

## Adapter 框架

核心代码围绕 adapter 组织：

```text
src/agent_tool_drift/adapters/
  base.py                 # AdapterContext 和 ToolAdapter 接口
  python_static.py        # Python AST decorator 扫描
  manifest.py             # JSON/YAML 工具 manifest
  openapi.py              # JSON/YAML OpenAPI / Swagger
  mcp_stdio.py            # MCP stdio server
  langchain_static.py     # LangChain @tool 和 StructuredTool.from_function
  openai_agents_static.py # OpenAI Agents SDK @function_tool
  registry.py             # 内置 adapter 和外部插件加载
```

所有 adapter 都输出同一个 `ToolContract` 模型，所以后续 diff、report、CI 逻辑不需要关心工具来自哪个框架。

通用 Python scanner 使用 AST，不会 import 用户代码。常见类型标注比如 `Optional`、`Union`、`Literal`、`Annotated`、`list[T]`、`dict[str, T]` 会被转换成近似 JSON Schema。

## OpenAI Agents SDK 检测

OpenAI Agents SDK 扫描默认关闭，避免和通用 Python decorator scanner 产生重复结果。需要框架级元数据时可以打开：

```yaml
python:
  enabled: false
openai_agents:
  enabled: true
```

支持这种写法：

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

这个 adapter 会读取函数签名、返回类型、docstring，以及 `function_tool(...)` 中的常见参数，比如 `name_override`、`description_override`、`use_docstring_info`、`defer_loading`。

如果第一个参数是 `RunContextWrapper`、`ctx`、`context` 或 `run_context`，它会被当成运行时上下文，不会出现在模型可调用的输入 schema 里。

参考：[OpenAI Agents SDK tools documentation](https://openai.github.io/openai-agents-python/tools/)。

## LangChain 检测

LangChain 扫描默认关闭，避免和通用 Python decorator scanner 重复。启用方式：

```yaml
python:
  enabled: false
langchain:
  enabled: true
```

支持常见写法：

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

`runtime` 和 `config` 这类 LangChain 注入参数会从工具输入 schema 中隐藏。

## Manifest 检测

支持这些文件名：

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

示例：

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

## OpenAPI 检测

支持：

- `openapi.json`
- `openapi.yaml`
- `openapi.yml`
- `swagger.json`
- `swagger.yaml`
- `swagger.yml`

每个 operation 会变成一个工具。优先使用 `operationId` 作为工具名，否则根据 HTTP method 和 path 生成名称。同一个文档内的本地 `$ref` 会在参数、request body、response 和嵌套 schema 中解析。

path 级参数和 operation 级参数会按 OpenAPI 覆盖语义合并。content 会优先选择 JSON 类型，包括 `application/vnd.api+json` 这类 vendor JSON media type。response 会识别带引号或不带引号的 2xx 成功状态码。
如果不同位置的参数重名，扫描器会加上位置前缀来区分，比如 `path_id` 和 `query_id`。如果已经存在名为 `body` 的参数，request body 会暴露为 `request_body`。

## MCP Stdio 检测

直接启动 MCP stdio server：

```bash
agent-tool-drift mcp-snapshot -o mcp-tools.json -- python examples/mcp_server/mock_server.py
```

从配置中运行 MCP server：

```bash
agent-tool-drift mcp-snapshot --config agent-tool-drift.yaml --server filesystem
```

## 什么算漂移

diff 引擎会检测：

- 工具删除
- 新增必填参数
- 输入参数删除
- 可能的输入参数重命名候选
- 输入/输出类型变化
- 输出字段删除
- default 默认值变化
- 数字、字符串、数组、对象约束收紧或放宽
- nullable 变化
- `additionalProperties` 行为变化
- 数组 `items` schema 变化
- `oneOf`、`anyOf`、`allOf` 组合 schema 变化
- 嵌套对象 `required` 字段变化
- 可能的 schema 字段重命名候选
- 描述变化
- 源码路径变化
- 工具版本变化
- 快照中记录到的依赖版本变化

默认策略偏保守：很可能破坏 Agent 调用的变化会被标成 `BREAKING`。

每次 diff 的 summary 里还会有一个确定性的兼容性评分：

- `compatibility_score`：从 `100` 开始，根据每个 drift 扣分。breaking 变化按完整权重扣分；uncertain 变化按较低权重扣分；backward-compatible 变化只扣很小的 review 分。
- `risk_level`：`low`、`medium`、`high` 或 `critical`。

这个分数故意设计得简单、稳定，适合 CI 和 PR 里做初筛。它不是运行时安全性的数学证明。

每条变化还包含：

- `domain`：`tool`、`input`、`schema`、`environment` 或 `unknown`。
- `operation`：归一化操作，例如 `added`、`removed`、`changed`、`narrowed`、`widened`、`rename_candidate`。
- `direction`：`input`、`output`、`tool`、`environment` 或 `bidirectional`。
- `compatibility`：`breaking`、`backward_compatible`、`uncertain` 或 `unknown`。
- `confidence`：直接确定的规则通常是 `1.0`，重命名这类推断会低一些。
- `evidence`：简短解释，比如重命名推断会记录 name similarity 和 schema similarity。

重命名候选是额外诊断，不会替代底层的 removed/added 变化。因为没有项目上下文时，扫描器不能证明这一定是重命名。

每个 `ContractChange` 还会带一个 `advice` 字段。它不会自动改代码，而是给 reviewer 一个通常更安全的迁移方向，比如：删除工具时先保留兼容包装、新增参数时优先做成可选参数、删除输出字段前先检查下游解析器。

advice 会明确标记为启发式建议。JSON 和 SARIF 报告里会包含：

- `advice`：默认迁移建议。
- `advice_kind`：当前是 `heuristic`。
- `advice_category`：`tool`、`input`、`schema`、`environment` 或 `unknown`。
- `agent_guidance`：提醒真正执行迁移的模型不要机械照做，而是先看源码、调用方、测试和业务上下文，再决定应用、改写或忽略这个建议。

内置规则在 `src/agent_tool_drift/advice.py`。这些规则是为了 CI 稳定和可复现，不是为了替代人或模型的判断。
团队可以在配置里用 `advice.overrides` 覆盖建议。覆盖值可以是普通字符串，也可以是带 `suggestion`、`kind`、`category`、`agent_guidance` 的对象。

## 外部 Adapter 插件

第三方包可以通过 Python entry point 暴露 adapter：

```toml
[project.entry-points."agent_tool_drift.adapters"]
my-framework = "my_package.tool_drift:MyFrameworkAdapter"
```

插件默认关闭，需要显式启用：

```yaml
plugins:
  enabled: true
  include:
    - my-framework
```

## GitHub Action

项目提供 composite GitHub Action：

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

Action 默认输出 GitHub annotations。SARIF 上传作为单独步骤保留，方便仓库自己决定是否启用 Code Scanning。

## Skill 入口

`skills/codex-tool-drift/SKILL.md` 是一个薄的 Codex skill 包装层。它告诉模型应该怎么运行 CLI、怎么解释报告；真正的扫描、diff、报告逻辑仍然在普通 Python 代码中。

这就是推荐结构：

- 通用代码框架是主体。
- CLI / GitHub Action / Python API 让所有人都能用。
- skill 只是给模型使用这个框架的入口之一。

## 当前限制

- Python 类型提取是近似的，不等同于完整类型检查器。
- 静态扫描不会 import 用户代码。动态生成的工具建议通过 MCP 或未来的 runtime adapter 暴露。
- OpenAPI `$ref` 当前支持同一文档内的本地引用，跨文件引用还需要扩展。
- OpenAI Agents SDK adapter 当前检测静态 `@function_tool`，不会执行 `Agent(...)` 构造逻辑。
