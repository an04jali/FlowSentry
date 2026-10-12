from __future__ import annotations

import json
import hashlib
import html
from typing import Any, Iterable, List, Mapping, Optional

from .diff import ContractChange, DiffResult
from .models import Snapshot, ToolContract


def snapshot_markdown(snapshot: Snapshot) -> str:
    lines = [
        "# Agent Tool Drift Snapshot",
        "",
        f"- Root: `{snapshot.root}`",
        f"- Generated: `{snapshot.generated_at}`",
        f"- Tools: `{len(snapshot.tools)}`",
        "",
    ]
    if not snapshot.tools:
        lines.append("No tools found.")
        return "\n".join(lines) + "\n"

    lines.extend(["| Tool | Kind | Source | Inputs | Description |", "|---|---|---|---|---|"])
    for tool in snapshot.sorted_tools():
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape(tool.name),
                    _escape(tool.kind),
                    _escape(_source(tool)),
                    _escape(", ".join(_input_names(tool)) or "-"),
                    _escape(_short(tool.description)),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def snapshot_html(snapshot: Snapshot) -> str:
    rows = []
    for tool in snapshot.sorted_tools():
        rows.append(
            "<tr>"
            f"<td>{_html(tool.name)}</td>"
            f"<td>{_html(tool.kind)}</td>"
            f"<td><code>{_html(_source(tool))}</code></td>"
            f"<td>{_html(', '.join(_input_names(tool)) or '-')}</td>"
            f"<td>{_html(_short(tool.description, 140))}</td>"
            "</tr>"
        )
    body = "\n".join(rows) if rows else "<tr><td colspan=\"5\">No tools found.</td></tr>"
    return _html_page(
        "Agent Tool Drift Snapshot",
        [
            f"<p><strong>Root:</strong> <code>{_html(snapshot.root)}</code></p>",
            f"<p><strong>Generated:</strong> <code>{_html(snapshot.generated_at)}</code></p>",
            f"<p><strong>Tools:</strong> {len(snapshot.tools)}</p>",
            "<table><thead><tr><th>Tool</th><th>Kind</th><th>Source</th><th>Inputs</th><th>Description</th></tr></thead>"
            f"<tbody>{body}</tbody></table>",
        ],
    )


def diff_markdown(diff: DiffResult) -> str:
    data = diff.to_dict()
    summary = data["summary"]
    lines = [
        "# Agent Tool Drift Report",
        "",
        f"- Breaking: `{summary['breaking']}`",
        f"- Warnings: `{summary['warnings']}`",
        f"- Info: `{summary['info']}`",
        f"- Total changes: `{summary['total']}`",
        f"- Compatibility score: `{summary['compatibility_score']}/100`",
        f"- Risk level: `{summary['risk_level']}`",
        "",
        "Advice is heuristic. A human reviewer or migration agent should inspect the source, callers, tests, and product context before applying, adapting, or ignoring it.",
        "",
    ]
    if not diff.changes:
        lines.append("No drift detected.")
        return "\n".join(lines) + "\n"

    lines.extend(["| Severity | Tool | Code | Message | Compatibility | Confidence | Advice |", "|---|---|---|---|---|---|---|"])
    for change in diff.sorted_changes():
        lines.append(
            "| "
            + " | ".join(
                [
                    change.severity,
                    _escape(change.tool),
                    _escape(change.code),
                    _escape(change.message),
                    _escape(change.compatibility),
                    f"{change.confidence:.2f}",
                    _escape(_advice_label(change)),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def diff_html(diff: DiffResult) -> str:
    summary = diff.to_dict()["summary"]
    rows = []
    for change in diff.sorted_changes():
        location = _change_location(change)
        location_text = "-"
        if location.source_path:
            location_text = location.source_path
            if location.source_line:
                location_text += f":{location.source_line}"
        rows.append(
            f"<tr class=\"severity-{_html_class(change.severity)}\">"
            f"<td>{_html(change.severity)}</td>"
            f"<td>{_html(change.tool)}</td>"
            f"<td><code>{_html(change.code)}</code></td>"
            f"<td><code>{_html(location_text)}</code></td>"
            f"<td>{_html(change.message)}</td>"
            f"<td>{_html(change.compatibility)}</td>"
            f"<td>{change.confidence:.2f}</td>"
            f"<td>{_html(_advice_label(change))}</td>"
            "</tr>"
        )
    body = "\n".join(rows) if rows else "<tr><td colspan=\"8\">No drift detected.</td></tr>"
    return _html_page(
        "Agent Tool Drift Report",
        [
            "<div class=\"summary\">"
            f"<span class=\"badge error\">Breaking: {summary['breaking']}</span>"
            f"<span class=\"badge warning\">Warnings: {summary['warnings']}</span>"
            f"<span class=\"badge note\">Info: {summary['info']}</span>"
            f"<span class=\"badge\">Total: {summary['total']}</span>"
            f"<span class=\"badge score\">Score: {summary['compatibility_score']}/100</span>"
            f"<span class=\"badge risk\">Risk: {_html(summary['risk_level'])}</span>"
            "</div>",
            "<p class=\"advice-note\">Advice is heuristic. A human reviewer or migration agent should inspect the source, callers, tests, and product context before applying, adapting, or ignoring it.</p>",
            "<table><thead><tr><th>Severity</th><th>Tool</th><th>Code</th><th>Location</th><th>Message</th><th>Compatibility</th><th>Confidence</th><th>Advice</th></tr></thead>"
            f"<tbody>{body}</tbody></table>",
        ],
    )


def diff_json(diff: DiffResult) -> str:
    return json.dumps(diff.to_dict(), indent=2, sort_keys=True) + "\n"


def diff_sarif(diff: DiffResult) -> str:
    rules = [_sarif_rule(code, changes) for code, changes in _changes_by_code(diff).items()]
    results = [_sarif_result(change) for change in diff.sorted_changes()]
    payload = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "agent-tool-drift",
                        "informationUri": "https://github.com/your-org/agent-tool-drift",
                        "rules": rules,
                    }
                },
                "results": results,
                "properties": {
                    "compatibilityScore": diff.compatibility_score,
                    "riskLevel": diff.risk_level,
                },
            }
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def github_annotations(diff: DiffResult) -> str:
    lines = []
    for change in diff.sorted_changes():
        command = _annotation_command(change)
        title = _annotation_property_escape(f"{change.code}: {change.tool}")
        message = _annotation_escape(_message_with_advice(change, include_agent_guidance=False))
        location = _change_location(change)
        properties = [f"title={title}"]
        if location.source_path and not _is_virtual_uri(location.source_path):
            properties.insert(0, f"file={_annotation_property_escape(location.source_path)}")
            if location.source_line:
                properties.insert(1, f"line={location.source_line}")
        lines.append(f"::{command} {','.join(properties)}::{message}")
    return "\n".join(lines) + ("\n" if lines else "")


def snapshot_json(snapshot: Snapshot) -> str:
    return json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n"


def _source(tool: ToolContract) -> str:
    if tool.source_line:
        return f"{tool.source_path}:{tool.source_line}"
    return tool.source_path


def _input_names(tool: ToolContract) -> List[str]:
    properties = tool.input_schema.get("properties")
    if not isinstance(properties, dict):
        return []
    required = set(tool.input_schema.get("required") or [])
    names = []
    for name in sorted(properties):
        suffix = "*" if name in required else ""
        names.append(f"{name}{suffix}")
    return names


def _short(value: str, limit: int = 90) -> str:
    clean = " ".join((value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _changes_by_code(diff: DiffResult) -> dict[str, list[ContractChange]]:
    result: dict[str, list[ContractChange]] = {}
    for change in diff.sorted_changes():
        result.setdefault(change.code, []).append(change)
    return result


def _sarif_rule(code: str, changes: list[ContractChange]) -> Mapping[str, Any]:
    highest = sorted(changes, key=lambda item: _level_rank(item.severity))[0]
    return {
        "id": code,
        "name": code,
        "shortDescription": {"text": code},
        "fullDescription": {"text": _message_with_advice(highest)},
        "defaultConfiguration": {"level": _sarif_level(highest.severity)},
        "properties": {
            "tags": ["agent-tools", "tool-contract-drift"],
            "adviceKind": highest.advice_kind,
            "adviceCategory": highest.advice_category,
            "agentGuidance": highest.agent_guidance,
        },
    }


def _sarif_result(change: ContractChange) -> Mapping[str, Any]:
    location = _change_location(change)
    result: dict[str, Any] = {
        "ruleId": change.code,
        "level": _sarif_level(change.severity),
        "message": {"text": f"{change.tool}: {_message_with_advice(change)}"},
        "partialFingerprints": {"agentToolDrift/v1": _fingerprint(change, location)},
        "properties": {
            "advice": change.advice,
            "adviceKind": change.advice_kind,
            "adviceCategory": change.advice_category,
            "agentGuidance": change.agent_guidance,
            "confidence": change.confidence,
            "evidence": change.evidence,
            "domain": change.domain,
            "operation": change.operation,
            "direction": change.direction,
            "compatibility": change.compatibility,
        },
    }
    if location.source_path:
        physical: dict[str, Any] = {
            "artifactLocation": {"uri": location.source_path.replace("\\", "/")},
        }
        if location.source_line:
            physical["region"] = {"startLine": location.source_line}
        result["locations"] = [{"physicalLocation": physical}]
    return result


def _message_with_advice(change: ContractChange, include_agent_guidance: bool = True) -> str:
    if not change.advice:
        return change.message
    message = f"{change.message} Advice ({change.advice_kind}): {change.advice}"
    if include_agent_guidance and change.agent_guidance:
        message += f" Agent guidance: {change.agent_guidance}"
    return message


def _advice_label(change: ContractChange) -> str:
    if not change.advice:
        return "-"
    return f"{change.advice} ({change.advice_kind})"


class _Location:
    def __init__(self, source_path: Optional[str], source_line: Optional[int]) -> None:
        self.source_path = source_path
        self.source_line = source_line


def _change_location(change: ContractChange) -> _Location:
    if change.source_path:
        return _Location(change.source_path, change.source_line)
    contract = _contract_dict(change.after) or _contract_dict(change.before)
    if not contract:
        return _Location(None, None)
    source_path = contract.get("source_path")
    source_line = contract.get("source_line")
    return _Location(
        str(source_path) if source_path else None,
        int(source_line) if isinstance(source_line, int) else None,
    )


def _contract_dict(value: Any) -> Optional[Mapping[str, Any]]:
    return value if isinstance(value, Mapping) and "source_path" in value else None


def _sarif_level(severity: str) -> str:
    if severity == "BREAKING":
        return "error"
    if severity == "WARNING":
        return "warning"
    return "note"


def _annotation_command(change: ContractChange) -> str:
    if change.severity == "BREAKING":
        return "error"
    if change.severity == "WARNING":
        return "warning"
    return "notice"


def _level_rank(severity: str) -> int:
    return {"BREAKING": 0, "WARNING": 1, "INFO": 2}.get(severity, 99)


def _fingerprint(change: ContractChange, location: _Location) -> str:
    text = "|".join(
        [
            change.code,
            change.tool,
            location.source_path or "",
            str(location.source_line or ""),
            change.message,
        ]
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _annotation_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _annotation_property_escape(value: str) -> str:
    return _annotation_escape(value).replace(",", "%2C").replace(":", "%3A")


def _is_virtual_uri(value: str) -> bool:
    return "://" in value


def _html(value: object) -> str:
    return html.escape(str(value), quote=True)


def _html_class(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value)


def _html_page(title: str, parts: list[str]) -> str:
    body = "\n".join(parts)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>{_html(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; }}
    h1 {{ font-size: 24px; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #d5d8dc; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f4f6f7; }}
    code {{ background: #f4f6f7; padding: 1px 4px; border-radius: 4px; }}
    .summary {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }}
    .badge {{ display: inline-block; border: 1px solid #d5d8dc; border-radius: 999px; padding: 4px 10px; background: #f8f9f9; }}
    .badge.error, .severity-breaking td:first-child {{ color: #922b21; font-weight: 700; }}
    .badge.warning, .severity-warning td:first-child {{ color: #9a6a00; font-weight: 700; }}
    .badge.note, .severity-info td:first-child {{ color: #1f618d; font-weight: 700; }}
    .badge.score, .badge.risk {{ color: #1c2833; font-weight: 700; }}
    .advice-note {{ color: #566573; max-width: 960px; }}
  </style>
</head>
<body>
  <h1>{_html(title)}</h1>
  {body}
</body>
</html>
"""
