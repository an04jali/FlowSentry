from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

from ..models import ToolContract
from ..schema import annotation_to_schema, build_object_schema, literal_value, normalize_json_schema, schema_with_default
from .base import AdapterContext, ToolAdapter, relative_path, walk_matching_files


class PythonStaticAdapter(ToolAdapter):
    name = "python-static"

    def scan(self, context: AdapterContext) -> list[ToolContract]:
        contracts: list[ToolContract] = []
        for path in walk_matching_files(
            context.root,
            suffixes={".py"},
            include=context.config.python.include,
            exclude=context.config.python.exclude,
        ):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    decorator = _tool_decorator(node.decorator_list, context.config.python.decorators)
                    if decorator is None:
                        continue
                    contracts.append(_python_function_contract(context.root, path, node, decorator))
        return contracts


def scan_python_tools(root: Path, decorators: Sequence[str]) -> list[ToolContract]:
    from ..config import AgentToolDriftConfig, PythonConfig

    config = AgentToolDriftConfig(python=PythonConfig(decorators=tuple(decorators)))
    return PythonStaticAdapter().scan(AdapterContext(root=root, config=config))


def _python_function_contract(
    root: Path,
    path: Path,
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
    decorator: Mapping[str, Any],
) -> ToolContract:
    properties: Dict[str, Dict[str, Any]] = {}
    required: list[str] = []

    positional = list(node.args.posonlyargs) + list(node.args.args)
    positional_defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
    for arg, default in zip(positional, positional_defaults):
        if arg.arg in {"self", "cls"}:
            continue
        properties[arg.arg] = schema_with_default(annotation_to_schema(arg.annotation), default)
        if default is None:
            required.append(arg.arg)

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
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
    description = str(decorator.get("description") or _first_paragraph(docstring))
    name = str(decorator.get("name") or node.name)
    version = decorator.get("version")

    return ToolContract(
        name=name,
        kind="python",
        source_path=relative_path(root, path),
        source_line=node.lineno,
        version=str(version) if version is not None else None,
        description=description,
        input_schema=normalize_json_schema(input_schema),
        output_schema=normalize_json_schema(output_schema),
        metadata={
            "adapter": PythonStaticAdapter.name,
            "function_name": node.name,
            "decorator": decorator.get("decorator"),
            "async": isinstance(node, ast.AsyncFunctionDef),
        },
    )


def _tool_decorator(decorators: Sequence[ast.expr], configured_decorators: Sequence[str]) -> Optional[Dict[str, Any]]:
    decorator_names = set(configured_decorators)
    for decorator in decorators:
        name, call = _decorator_name_and_call(decorator)
        if not name:
            continue
        short_name = name.split(".")[-1]
        if name not in decorator_names and short_name not in decorator_names:
            continue
        details: Dict[str, Any] = {"decorator": name}
        if call is not None:
            if call.args:
                first = literal_value(call.args[0])
                if isinstance(first, str):
                    details["name"] = first
            for keyword in call.keywords:
                if keyword.arg in {"name", "description", "version"}:
                    value = literal_value(keyword.value)
                    if value is not None:
                        details[keyword.arg] = value
        return details
    return None


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


def _first_paragraph(text: str) -> str:
    return text.strip().split("\n\n", 1)[0].strip()
