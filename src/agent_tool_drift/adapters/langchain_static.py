from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple, Union

from ..models import ToolContract
from ..schema import annotation_to_schema, build_object_schema, literal_value, normalize_json_schema, schema_with_default
from .base import AdapterContext, ToolAdapter, relative_path, walk_matching_files


LANGCHAIN_IMPORT_PREFIXES = ("langchain", "langchain_core")
HIDDEN_TOOL_ARGUMENTS = {"runtime", "config"}


class LangChainStaticAdapter(ToolAdapter):
    name = "langchain-static"

    def scan(self, context: AdapterContext) -> list[ToolContract]:
        contracts: list[ToolContract] = []
        for path in walk_matching_files(
            context.root,
            suffixes={".py"},
            include=context.config.langchain.include,
            exclude=context.config.langchain.exclude,
        ):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            imports = _collect_langchain_imports(tree)
            if not imports.has_langchain_tools:
                continue
            functions = {
                node.name: node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            seen: set[tuple[str, int]] = set()
            for function in functions.values():
                decorator = _langchain_tool_decorator(function.decorator_list, imports)
                if decorator is None:
                    continue
                contract = _function_contract(context.root, path, function, decorator)
                seen.add((function.name, function.lineno))
                contracts.append(contract)

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call = _structured_tool_from_function_call(node, imports)
                if call is None:
                    continue
                function = functions.get(call.function_name) if call.function_name else None
                if function is not None:
                    key = (function.name, function.lineno)
                    if key in seen:
                        continue
                    seen.add(key)
                    contracts.append(_function_contract(context.root, path, function, call.details))
                else:
                    contracts.append(_call_contract(context.root, path, node, call.details))
        return contracts


class _LangChainImports:
    def __init__(self) -> None:
        self.tool_aliases: set[str] = set()
        self.structured_tool_aliases: set[str] = set()
        self.tool_class_aliases: set[str] = set()
        self.module_aliases: set[str] = set()

    @property
    def has_langchain_tools(self) -> bool:
        return bool(self.tool_aliases or self.structured_tool_aliases or self.tool_class_aliases or self.module_aliases)


class _FromFunctionCall:
    def __init__(self, function_name: Optional[str], details: Mapping[str, Any]) -> None:
        self.function_name = function_name
        self.details = details


def _collect_langchain_imports(tree: ast.AST) -> _LangChainImports:
    imports = _LangChainImports()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if not node.module.startswith(LANGCHAIN_IMPORT_PREFIXES):
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name
                if alias.name == "tool":
                    imports.tool_aliases.add(local_name)
                elif alias.name == "StructuredTool":
                    imports.structured_tool_aliases.add(local_name)
                elif alias.name == "Tool":
                    imports.tool_class_aliases.add(local_name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"langchain.tools", "langchain_core.tools"}:
                    imports.module_aliases.add(alias.asname or alias.name)
    return imports


def _langchain_tool_decorator(decorators: Sequence[ast.expr], imports: _LangChainImports) -> Optional[Dict[str, Any]]:
    for decorator in decorators:
        name, call = _decorator_name_and_call(decorator)
        if not name or not _is_tool_name(name, imports):
            continue
        details: Dict[str, Any] = {"decorator": name}
        if call is not None:
            if call.args:
                first = literal_value(call.args[0])
                if isinstance(first, str):
                    details["name"] = first
            for keyword in call.keywords:
                if keyword.arg in {"name", "description", "response_format", "parse_docstring"}:
                    value = literal_value(keyword.value)
                    if value is not None:
                        details[keyword.arg] = value
                elif keyword.arg == "args_schema":
                    details["args_schema"] = _dotted_name(keyword.value) or ast.unparse(keyword.value)
        return details
    return None


def _structured_tool_from_function_call(node: ast.Call, imports: _LangChainImports) -> Optional[_FromFunctionCall]:
    if not _is_from_function_call(node.func, imports):
        return None
    function_name = None
    if node.args:
        function_name = _dotted_name(node.args[0])
    details: Dict[str, Any] = {"factory": _dotted_name(node.func) or "from_function"}
    for keyword in node.keywords:
        if keyword.arg in {"func", "coroutine"}:
            function_name = _dotted_name(keyword.value)
        elif keyword.arg in {"name", "description", "response_format", "parse_docstring"}:
            value = literal_value(keyword.value)
            if value is not None:
                details[keyword.arg] = value
        elif keyword.arg == "args_schema":
            details["args_schema"] = _dotted_name(keyword.value) or ast.unparse(keyword.value)
    if function_name and "." in function_name:
        function_name = function_name.rsplit(".", 1)[-1]
    return _FromFunctionCall(function_name=function_name, details=details)


def _is_tool_name(name: str, imports: _LangChainImports) -> bool:
    if name in imports.tool_aliases:
        return True
    if "." in name:
        module_name, attr = name.rsplit(".", 1)
        return attr == "tool" and module_name in imports.module_aliases
    return False


def _is_from_function_call(node: ast.AST, imports: _LangChainImports) -> bool:
    dotted = _dotted_name(node)
    if not dotted or not dotted.endswith(".from_function"):
        return False
    owner = dotted[: -len(".from_function")]
    if owner in imports.structured_tool_aliases or owner in imports.tool_class_aliases:
        return True
    if "." in owner:
        module_name, class_name = owner.rsplit(".", 1)
        return module_name in imports.module_aliases and class_name in {"StructuredTool", "Tool"}
    return False


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
    for arg, default in zip(positional, positional_defaults):
        if arg.arg in {"self", "cls"} or arg.arg in HIDDEN_TOOL_ARGUMENTS:
            continue
        properties[arg.arg] = schema_with_default(annotation_to_schema(arg.annotation), default)
        if default is None:
            required.append(arg.arg)

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        if arg.arg in HIDDEN_TOOL_ARGUMENTS:
            continue
        properties[arg.arg] = schema_with_default(annotation_to_schema(arg.annotation), default)
        if default is None:
            required.append(arg.arg)

    input_schema = build_object_schema(properties, required)
    output_schema = annotation_to_schema(node.returns)
    docstring = ast.get_docstring(node) or ""
    description = str(details.get("description") or _first_paragraph(docstring))
    name = str(details.get("name") or node.name)

    metadata = {
        "adapter": LangChainStaticAdapter.name,
        "function_name": node.name,
        "async": isinstance(node, ast.AsyncFunctionDef),
    }
    metadata.update({key: value for key, value in details.items() if key not in {"name", "description"}})

    return ToolContract(
        name=name,
        kind="langchain",
        source_path=relative_path(root, path),
        source_line=node.lineno,
        version=None,
        description=description,
        input_schema=normalize_json_schema(input_schema),
        output_schema=normalize_json_schema(output_schema),
        metadata=metadata,
    )


def _call_contract(root: Path, path: Path, call: ast.Call, details: Mapping[str, Any]) -> ToolContract:
    name = str(details.get("name") or f"langchain_tool_{call.lineno}")
    description = str(details.get("description") or "")
    return ToolContract(
        name=name,
        kind="langchain",
        source_path=relative_path(root, path),
        source_line=call.lineno,
        version=None,
        description=description,
        input_schema={},
        output_schema={},
        metadata={"adapter": LangChainStaticAdapter.name, **dict(details)},
    )


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
