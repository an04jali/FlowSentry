from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

from .adapters import adapter_status
from .adapters.mcp_stdio import snapshot_configured_mcp_servers
from .config import AgentToolDriftConfig, default_config, load_config, write_default_config
from .diff import DiffResult, apply_advice_config, compare_snapshots
from .dependency_graph import DependencyGraph
from .impact import analyze_change_impact
from .io import load_snapshot, save_snapshot, write_text
from .mcp_client import McpClientError, McpSnapshotOptions, snapshot_from_mcp_stdio
from .report import (
    diff_html,
    diff_json,
    diff_markdown,
    diff_sarif,
    github_annotations,
    snapshot_html,
    snapshot_json,
    snapshot_markdown,
)
from .scanner import scan_project


DEFAULT_BASELINE_PATH = ".agent-tool-drift/snapshot.json"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-tool-drift",
        description="Detect drift between agent tool contracts and source code.",
    )
    parser.add_argument("--version", action="version", version="agent-tool-drift 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create an agent-tool-drift configuration file.")
    init.add_argument("-o", "--output", default="agent-tool-drift.yaml", help="Configuration file to create.")
    init.add_argument("--force", action="store_true", help="Overwrite an existing configuration file.")
    init.set_defaults(func=_init_command)

    adapters = subparsers.add_parser("adapters", help="List built-in and configured external adapters.")
    adapters.add_argument("path", nargs="?", default=".", help="Project path for config auto-discovery.")
    adapters.add_argument("--config", help="Configuration file. Auto-discovered by default.")
    adapters.add_argument("--format", choices=["json", "markdown"], default="markdown", help="Output format.")
    adapters.set_defaults(func=_adapters_command)

    doctor = subparsers.add_parser("doctor", help="Validate configuration and summarize enabled scanners.")
    doctor.add_argument("path", nargs="?", default=".", help="Project path to inspect.")
    doctor.add_argument("--config", help="Configuration file. Auto-discovered by default.")
    doctor.add_argument("--format", choices=["json", "markdown"], default="markdown", help="Output format.")
    doctor.set_defaults(func=_doctor_command)

    snapshot = subparsers.add_parser("snapshot", help="Scan a project and emit a tool contract snapshot.")
    snapshot.add_argument("path", nargs="?", default=".", help="Project path to scan.")
    snapshot.add_argument("--config", help="Configuration file. Auto-discovered by default.")
    snapshot.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    snapshot.add_argument("--format", choices=["json", "markdown", "html"], default="json", help="Output format.")
    snapshot.set_defaults(func=_snapshot_command)

    mcp_snapshot = subparsers.add_parser("mcp-snapshot", help="Launch an MCP stdio server and snapshot its tools.")
    mcp_snapshot.add_argument("--config", help="Configuration file containing mcp.servers entries.")
    mcp_snapshot.add_argument("--server", action="append", help="Configured MCP server name to snapshot. Repeatable.")
    mcp_snapshot.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    mcp_snapshot.add_argument("--format", choices=["json", "markdown", "html"], default="json", help="Output format.")
    mcp_snapshot.add_argument("--cwd", help="Working directory for the MCP server command.")
    mcp_snapshot.add_argument("--timeout", type=float, default=10.0, help="Timeout in seconds for each MCP request.")
    mcp_snapshot.add_argument("--server-name", help="Override the server name used in snapshot source paths.")
    mcp_snapshot.add_argument(
        "--protocol-version",
        default="2025-06-18",
        help="MCP protocol version to send during initialize.",
    )
    mcp_snapshot.add_argument("command", nargs=argparse.REMAINDER, help="MCP server command, usually after --.")
    mcp_snapshot.set_defaults(func=_mcp_snapshot_command)

    diff = subparsers.add_parser("diff", help="Compare two snapshot JSON files.")
    diff.add_argument("before", help="Old snapshot JSON file.")
    diff.add_argument("after", help="New snapshot JSON file.")
    diff.add_argument("--config", help="Configuration file for policy.ignore and policy.fail_on.")
    diff.add_argument("-o", "--output", help="Output file. Defaults to stdout.")
    diff.add_argument("--format", choices=["json", "markdown", "sarif", "html"], default="markdown", help="Output format.")
    diff.add_argument("--github-annotations", action="store_true", help="Also print GitHub Actions annotations to stderr.")
    diff.add_argument("--fail-on-breaking", action="store_true", help="Exit with status 2 if breaking drift is found.")
    diff.add_argument("--fail-on-policy", action="store_true", help="Exit with status 2 if any non-ignored change matches policy.fail_on.")
    diff.set_defaults(func=_diff_command)

    check = subparsers.add_parser("check", help="Scan a project and compare it with a baseline snapshot.")
    check.add_argument("path", nargs="?", default=".", help="Project path to scan.")
    check.add_argument("--config", help="Configuration file. Auto-discovered by default.")
    check.add_argument("--baseline", default=DEFAULT_BASELINE_PATH, help="Baseline snapshot path.")
    check.add_argument("-o", "--output", help="Report output file. Defaults to stdout.")
    check.add_argument("--format", choices=["json", "markdown", "sarif", "html"], default="markdown", help="Report format.")
    check.add_argument("--github-annotations", action="store_true", help="Also print GitHub Actions annotations to stderr.")
    check.add_argument("--update-baseline", action="store_true", help="Overwrite the baseline with the current snapshot after checking.")
    check.add_argument("--fail-on-breaking", action="store_true", help="Exit with status 2 if breaking drift is found.")
    check.add_argument("--fail-on-policy", action="store_true", help="Exit with status 2 if any non-ignored change matches policy.fail_on.")
    check.set_defaults(func=_check_command)
    impact = subparsers.add_parser(
        "impact",
        help="Analyze affected workflows and regression tests.",
    )
    impact.add_argument("before", help="Old snapshot JSON file.")
    impact.add_argument("after", help="New snapshot JSON file.")
    impact.add_argument(
        "--config",
        required=True,
        help="Configuration file defining workflow dependencies.",
    )
    impact.add_argument("-o", "--output", help="Report output file.")
    impact.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Impact report format.",
    )
    impact.set_defaults(func=_impact_command)

    return parser


def _init_command(args: argparse.Namespace) -> int:
    try:
        path = write_default_config(Path(args.output), force=args.force)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Created configuration file at {path}", file=sys.stderr)
    return 0


def _adapters_command(args: argparse.Namespace) -> int:
    config = load_config(args.config, root=Path(args.path))
    statuses = adapter_status(config)
    if args.format == "json":
        text = json.dumps({"adapters": [status.to_dict() for status in statuses]}, indent=2, sort_keys=True) + "\n"
    else:
        text = _adapter_status_markdown(statuses)
    print(text, end="")
    return 0


def _doctor_command(args: argparse.Namespace) -> int:
    project_path = Path(args.path)
    config = load_config(args.config, root=project_path)
    snapshot = scan_project(project_path, config=config)
    data = _doctor_data(project_path, config, snapshot)
    if args.format == "json":
        text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    else:
        text = _doctor_markdown(data)
    print(text, end="")
    return 0


def _snapshot_command(args: argparse.Namespace) -> int:
    project_path = Path(args.path)
    config = load_config(args.config, root=project_path)
    snapshot = scan_project(project_path, config=config)
    text = _format_snapshot(snapshot, args.format)
    _emit(text, args.output)
    return 0


def _mcp_snapshot_command(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        return _configured_mcp_snapshot_command(args)
    try:
        snapshot = snapshot_from_mcp_stdio(
            McpSnapshotOptions(
                command=command,
                cwd=Path(args.cwd) if args.cwd else None,
                timeout=args.timeout,
                protocol_version=args.protocol_version,
                server_name=args.server_name,
            )
        )
    except McpClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    text = _format_snapshot(snapshot, args.format)
    _emit(text, args.output)
    return 0


def _configured_mcp_snapshot_command(args: argparse.Namespace) -> int:
    root = Path(args.cwd).resolve() if args.cwd else Path(".").resolve()
    config = load_config(args.config, root=root)
    if not config.mcp.servers:
        print(
            "No MCP command was provided and no mcp.servers entries were found in configuration.",
            file=sys.stderr,
        )
        return 2
    missing = sorted(set(args.server or []) - set(config.mcp.servers))
    if missing:
        print(f"Unknown configured MCP server(s): {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        snapshot = snapshot_configured_mcp_servers(config, root=root, server_names=args.server)
    except McpClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    text = _format_snapshot(snapshot, args.format)
    _emit(text, args.output)
    return 0

def _impact_command(args: argparse.Namespace) -> int:
    before = load_snapshot(Path(args.before))
    after = load_snapshot(Path(args.after))
    config = load_config(args.config)

    diff_result = _prepare_diff(
        compare_snapshots(before, after),
        config,
    )
    graph = DependencyGraph.from_config(config)
    report = analyze_change_impact(diff_result, graph)

    if args.format == "json":
        output_text = json.dumps(
            {
                "changed_tools": report.changed_tools,
                "breaking_tools": report.breaking_tools,
                "affected_workflows": report.affected_workflows,
                "selected_tests": report.selected_tests,
            },
            indent=2,
            sort_keys=True,
        ) + "\n"
    else:
        sections = [
            "# Change Impact Report",
            "",
            "## Changed tools",
            *([f"- {x}" for x in report.changed_tools] or ["- None"]),
            "",
            "## Breaking tools",
            *([f"- {x}" for x in report.breaking_tools] or ["- None"]),
            "",
            "## Affected workflows",
            *([f"- {x}" for x in report.affected_workflows] or ["- None"]),
            "",
            "## Selected regression tests",
            *([f"- {x}" for x in report.selected_tests] or ["- None"]),
            "",
        ]
        output_text = "\n".join(sections)

    _emit(output_text, args.output)
    return 0

def _diff_command(args: argparse.Namespace) -> int:
    before = load_snapshot(Path(args.before))
    after = load_snapshot(Path(args.after))
    config = load_config(args.config) if args.config else default_config()
    result = _prepare_diff(compare_snapshots(before, after), config)
    text = _format_diff(result, args.format)
    _emit(text, args.output)
    _emit_annotations(result, args.github_annotations)
    if args.fail_on_policy and _policy_has_failure(result, config):
        return 2
    if args.fail_on_breaking and result.has_breaking:
        return 2
    return 0


def _check_command(args: argparse.Namespace) -> int:
    project_path = Path(args.path)
    baseline_path = _resolve_baseline_path(project_path, args.baseline)
    config = load_config(args.config, root=project_path)
    current = scan_project(project_path, config=config)

    if not baseline_path.exists():
        save_snapshot(baseline_path, current)
        result = _prepare_diff(compare_snapshots(current, current), config)
        text = _format_diff(result, args.format)
        _emit(text, args.output)
        _emit_annotations(result, args.github_annotations)
        print(f"Created baseline snapshot at {baseline_path}", file=sys.stderr)
        return 0

    baseline = load_snapshot(baseline_path)
    result = _prepare_diff(compare_snapshots(baseline, current), config)
    text = _format_diff(result, args.format)
    _emit(text, args.output)
    _emit_annotations(result, args.github_annotations)

    if args.update_baseline:
        save_snapshot(baseline_path, current)
        print(f"Updated baseline snapshot at {baseline_path}", file=sys.stderr)

    if args.fail_on_policy and _policy_has_failure(result, config):
        return 2
    if args.fail_on_breaking and result.has_breaking:
        return 2
    return 0


def _resolve_baseline_path(project_path: Path, baseline: str) -> Path:
    path = Path(baseline)
    if path.is_absolute() or baseline != DEFAULT_BASELINE_PATH:
        return path
    return project_path / path


def _apply_policy(result: DiffResult, config: AgentToolDriftConfig) -> DiffResult:
    ignored = tuple(config.policy.ignore)
    if not ignored:
        return result
    changes = [change for change in result.changes if not any(_policy_matches(change, selector) for selector in ignored)]
    return DiffResult(before_root=result.before_root, after_root=result.after_root, changes=changes)


def _prepare_diff(result: DiffResult, config: AgentToolDriftConfig) -> DiffResult:
    return _apply_policy(apply_advice_config(result, config.advice), config)


def _policy_has_failure(result: DiffResult, config: AgentToolDriftConfig) -> bool:
    fail_on = tuple(config.policy.fail_on)
    return any(_policy_matches(change, selector) for change in result.changes for selector in fail_on)


def _policy_matches(change, selector: str) -> bool:
    selector = str(selector).strip()
    normalized = selector.lower()
    return normalized in {
        change.code,
        f"severity:{change.severity.lower()}",
        f"compatibility:{change.compatibility}",
        f"domain:{change.domain}",
        f"operation:{change.operation}",
        f"direction:{change.direction}",
    }


def _format_diff(result: DiffResult, output_format: str) -> str:
    if output_format == "json":
        return diff_json(result)
    if output_format == "sarif":
        return diff_sarif(result)
    if output_format == "html":
        return diff_html(result)
    return diff_markdown(result)


def _format_snapshot(snapshot, output_format: str) -> str:
    if output_format == "markdown":
        return snapshot_markdown(snapshot)
    if output_format == "html":
        return snapshot_html(snapshot)
    return snapshot_json(snapshot)


def _emit_annotations(result: DiffResult, enabled: bool) -> None:
    if enabled:
        print(github_annotations(result), end="", file=sys.stderr)


def _emit(text: str, output: Optional[str]) -> None:
    if output:
        write_text(Path(output), text)
    else:
        print(text, end="")


def _adapter_status_markdown(statuses) -> str:
    lines = ["# Agent Tool Drift Adapters", "", "| Adapter | Source | Enabled | Reason |", "|---|---|---|---|"]
    for status in statuses:
        enabled = "yes" if status.enabled else "no"
        lines.append(f"| {status.name} | {status.source} | {enabled} | {status.reason} |")
    return "\n".join(lines) + "\n"


def _doctor_data(project_path: Path, config: AgentToolDriftConfig, snapshot) -> dict:
    by_kind = Counter(tool.kind for tool in snapshot.tools)
    by_adapter = Counter(str(tool.metadata.get("adapter", tool.kind)) for tool in snapshot.tools)
    return {
        "root": str(project_path.resolve()),
        "config_path": str(config.source_path) if config.source_path else None,
        "tool_count": len(snapshot.tools),
        "tools_by_kind": dict(sorted(by_kind.items())),
        "tools_by_adapter": dict(sorted(by_adapter.items())),
        "adapters": [status.to_dict() for status in adapter_status(config)],
        "adapter_errors": snapshot.environment.get("adapter_errors", []),
    }


def _doctor_markdown(data: dict) -> str:
    lines = [
        "# Agent Tool Drift Doctor",
        "",
        f"- Root: `{data['root']}`",
        f"- Config: `{data['config_path'] or 'auto defaults'}`",
        f"- Tools found: `{data['tool_count']}`",
        "",
        "## Tools By Kind",
        "",
    ]
    if data["tools_by_kind"]:
        for kind, count in data["tools_by_kind"].items():
            lines.append(f"- `{kind}`: {count}")
    else:
        lines.append("- No tools found.")
    lines.extend(["", "## Enabled Adapters", ""])
    for status in data["adapters"]:
        if status["enabled"]:
            lines.append(f"- `{status['name']}` ({status['source']}): {status['reason']}")
    if data["adapter_errors"]:
        lines.extend(["", "## Adapter Errors", ""])
        for error in data["adapter_errors"]:
            lines.append(f"- `{error.get('adapter', 'unknown')}`: {error.get('error', '')}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
