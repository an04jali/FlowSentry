from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

from ..models import ToolContract
from ..schema import annotation_to_schema, build_object_schema, literal_value, normalize_json_schema, schema_with_default
from .base import AdapterContext, ToolAdapter, relative_path, walk_matching_files


OPENAI_AGENTS_IMPORT_ROOTS = {"agents"}
HIDDEN_CONTEXT_NAMES = {"ctx", "context", "run_context"}


class OpenAIAgentsStaticAdapter(ToolAdapter):
    name = "openai-agents-static"

    def scan(self, context: AdapterContext) -> list[ToolContract]:
        contracts: list[ToolContract] = []
        for path in walk_matching_files(
            context.root,
            suffixes={".py"},
            include=context.config.openai_agents.include,
            exclude=context.config.openai_agents.exclude,
        ):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            imports = _collect_openai_agents_imports(tree)
            if not imports.has_function_tool:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decorator = _function_tool_decorator(node.decorator_list, imports)
                if decorator is None:
                    continue
                contracts.append(_function_contract(context.root, path, node, decorator))
        return contracts


class _OpenAIAgentsImports:
    def __init__(self) -> None:
        self.function_tool_aliases: set[str] = set()
        self.module_aliases: set[str] = set()

    @property
    def has_function_tool(self) -> bool:
        return bool(self.function_tool_aliases or self.module_aliases)


def _collect_openai_agents_imports(tree: ast.AST) -> _OpenAIAgentsImports:
    imports = _OpenAIAgentsImports()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module not in OPENAI_AGENTS_IMPORT_ROOTS:
                continue
            for alias in node.names:
                if alias.name == "function_tool":
                    imports.function_tool_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in OPENAI_AGENTS_IMPORT_ROOTS:
                    imports.module_aliases.add(alias.asname or alias.name)
    return imports


def _function_tool_decorator(
    decorators: Sequence[ast.expr],
    imports: _OpenAIAgentsImports,
) -> Optional[Dict[str, Any]]:
    for decorator in decorators:
        name, call = _decorator_name_and_call(decorator)
        if not name or not _is_function_tool_name(name, imports):
            continue
        details: Dict[str, Any] = {"decorator": name}
        if call is not None:
            if call.args:
                first = literal_value(call.args[0])
                if isinstance(first, str):
                    details["name"] = first
            for keyword in call.keywords:
                if keyword.arg is None:
                    continue
                value = literal_value(keyword.value)
                if keyword.arg == "name_override" and isinstance(value, str):
                    details["name"] = value
                    details["name_override"] = value
                elif keyword.arg == "description_override" and isinstance(value, str):
                    details["description"] = value
                    details["description_override"] = value
                elif keyword.arg in {
                    "use_docstring_info",
                    "failure_error_function",
                    "is_enabled",
                    "defer_loading",
                    "strict_mode",
                    "timeout",
                }:
                    details[keyword.arg] = value if value is not None else _expression_text(keyword.value)
                elif keyword.arg in {"docstring_style"}:
                    details[keyword.arg] = value if value is not None else _expression_text(keyword.value)
        return details
    return None


def _function_contract(
    root: Path,
    path: Path,
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    details: Mapping[str, Any],
) -> ToolContract:
    properties: Dict[str, Dict[str, Any]] = {}
    required: list[str] = []

    positional = list(node.args.posonlyargs) + list(node.args.args)
    positional_defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
    for index, (arg, default) in enumerate(zip(positional, positional_defaults)):
        if arg.arg in {"self", "cls"} or _is_hidden_context_arg(arg, index):
            continue
        properties[arg.arg] = schema_with_default(annotation_to_schema(arg.annotation), default)
        if default is None:
            required.append(arg.arg)

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        if _is_run_context_annotation(arg):
            continue
        properties[arg.arg] = schema_with_default(annotation_to_schema(arg.annotation), default)
        if default is None:
            required.append(arg.arg)

    if node.args.vararg:
        properties[node.args.vararg.arg] = {"type": "array", "metadata": {"vararg": True}}
    if node.args.kwarg:
        properties[node.args.kwarg.arg] = {"type": "object", "metadata": {"kwarg": True}}

    input_schema = build_object_schema(properties, required)
    output_schema = annotation_to_schema(node.returns)
    docstring = ast.get_docstring(node) or ""
    description = str(details.get("description") or _first_paragraph(docstring))
    name = str(details.get("name") or node.name)

    metadata = {
        "adapter": OpenAIAgentsStaticAdapter.name,
        "function_name": node.name,
        "decorator": details.get("decorator"),
        "async": isinstance(node, ast.AsyncFunctionDef),
    }
    metadata.update({key: value for key, value in details.items() if key not in {"name", "description", "decorator"}})

    return ToolContract(
        name=name,
        kind="openai-agents",
        source_path=relative_path(root, path),
        source_line=node.lineno,
        version=None,
        description=description,
        input_schema=normalize_json_schema(input_schema),
        output_schema=normalize_json_schema(output_schema),
        metadata=metadata,
    )


def _is_function_tool_name(name: str, imports: _OpenAIAgentsImports) -> bool:
    if name in imports.function_tool_aliases:
        return True
    if "." in name:
        module_name, attr = name.rsplit(".", 1)
        return attr == "function_tool" and module_name in imports.module_aliases
    return False


def _is_hidden_context_arg(arg: ast.arg, index: int) -> bool:
    if index != 0:
        return False
    if arg.arg in HIDDEN_CONTEXT_NAMES:
        return True
    return _is_run_context_annotation(arg)


def _is_run_context_annotation(arg: ast.arg) -> bool:
    annotation = _expression_text(arg.annotation)
    return bool(annotation and "RunContextWrapper" in annotation)


def _decorator_name_and_call(decorator: ast.expr) -> Tuple[Optional[str], Optional[ast.Call]]:
    if isinstance(decorator, ast.Call):
        return _dotted_name(decorator.func), decorator
    return _dotted_name(decorator), None


def _dotted_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _expression_text(node: Optional[ast.AST]) -> Optional[str]:
    if node is None:
        return None
    return ast.unparse(node) if hasattr(ast, "unparse") else None


def _first_paragraph(text: str) -> str:
    return text.strip().split("\n\n", 1)[0].strip()
