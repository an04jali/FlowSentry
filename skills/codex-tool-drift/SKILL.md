---
name: codex-tool-drift
description: Detect agent tool contract drift after tool library, schema, MCP, OpenAPI, LangChain, OpenAI Agents SDK, or source-code updates by running the agent-tool-drift CLI and interpreting the report.
---

# Codex Tool Drift

Use this skill when the user asks whether an agent's tool library update changed
tool interfaces, source locations, descriptions, runtime versions, or schemas.
The underlying scanner supports Python decorators, JSON/YAML tool manifests, and
JSON/YAML OpenAPI specs. It can also launch MCP stdio servers and snapshot their
advertised `tools/list` contracts.
It supports LangChain static scanning when `langchain.enabled: true` is set.
It supports OpenAI Agents SDK static scanning when `openai_agents.enabled: true`
is set.
It can load external adapter plugins only when `plugins.enabled: true` is set.
Prefer a checked-in `agent-tool-drift.yaml` when present; otherwise run
`agent-tool-drift init` to create one before setting project-specific patterns.

## Workflow

1. Find the project root and install the local package if needed:

   ```bash
   pip install -e .
   ```

2. Create or refresh a snapshot:

   ```bash
   agent-tool-drift snapshot . --config agent-tool-drift.yaml -o .agent-tool-drift/current.json
   ```

3. Compare against the known baseline:

   ```bash
   agent-tool-drift diff .agent-tool-drift/baseline.json .agent-tool-drift/current.json --config agent-tool-drift.yaml --format markdown
   ```

4. For CI-style checks with GitHub annotations:

   ```bash
   agent-tool-drift check . --config agent-tool-drift.yaml --baseline .agent-tool-drift/snapshot.json --format sarif -o agent-tool-drift.sarif --github-annotations --fail-on-policy
   ```

5. When a breaking change is intentional and reviewed, update the baseline:

   ```bash
   agent-tool-drift check . --baseline .agent-tool-drift/snapshot.json --update-baseline
   ```

6. For MCP stdio servers, snapshot the live server command:

   ```bash
   agent-tool-drift mcp-snapshot -o .agent-tool-drift/mcp.json -- python path/to/server.py
   ```

7. For configured MCP servers, run by name:

   ```bash
   agent-tool-drift mcp-snapshot --config agent-tool-drift.yaml --server filesystem -o .agent-tool-drift/mcp.json
   ```

8. If setup seems wrong, inspect adapters and run doctor:

   ```bash
   agent-tool-drift adapters . --config agent-tool-drift.yaml
   agent-tool-drift doctor . --config agent-tool-drift.yaml
   ```

## Interpretation

- `BREAKING`: likely to break agent tool calls or downstream parsing.
- `WARNING`: behavior, description, or output shape may have drifted.
- `INFO`: additive or contextual changes that should be reviewed.
- `compatibility_score`: deterministic CI triage score from 0 to 100, with
  breaking changes weighted more heavily than uncertain or backward-compatible
  changes.
- `risk_level`: `low`, `medium`, `high`, or `critical`.

Policy selectors can be exact change codes, such as `input.required_added`, or
semantic selectors, such as `compatibility:breaking`, `severity:BREAKING`,
`domain:input`, `operation:narrowed`, and `direction:output`. Prefer
`compatibility:breaking` as the default CI gate because some schema changes are
direction-sensitive. `policy.ignore` uses the same selector forms.

The diff engine performs deep JSON Schema checks. Mention changes to defaults,
constraints, nullability, `additionalProperties`, array `items`, composition
keywords such as `oneOf`/`anyOf`/`allOf`, and nested `required` fields when they
appear in the report.
It can infer likely input or schema property rename candidates. Report these as
extra uncertain diagnostics, not replacements for the underlying removed/added
changes, and include `confidence`, `evidence`, and `compatibility` when relevant.

When reporting results, group the highest-severity changes first and mention
whether the scanner found Python, manifest, or OpenAPI tools.
Mention LangChain separately when `kind: langchain` tools are found.
Mention OpenAI Agents SDK separately when `kind: openai-agents` tools are found.
Include the `advice` text for breaking or high-risk changes, because it explains
the usual migration path.
Treat advice as heuristic guidance, not an instruction to edit blindly. When
asked to fix drift, inspect source code, callers, tests, and project context,
then decide whether to apply, adapt, or ignore the built-in suggestion.
Respect `advice.overrides` in config; project-specific advice should be treated
as stronger local guidance than the built-in generic rule, but still not as a
blind edit command.
If `policy.ignore` is configured, mention that ignored changes were omitted from
the report.
