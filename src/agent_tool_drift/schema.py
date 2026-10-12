from __future__ import annotations

import ast
from typing import Any, Dict, Iterable, List, Optional, Sequence

_MISSING_LITERAL = object()


def annotation_to_schema(node: Optional[ast.AST]) -> Dict[str, Any]:
    if node is None:
        return {}

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return {"metadata": {"annotation": node.value}}

    text = ast.unparse(node) if hasattr(ast, "unparse") else ""
    simple = _simple_annotation_name(node)
    if simple:
        mapped = _SIMPLE_TYPE_MAP.get(simple)
        if mapped:
            return {"type": mapped, "metadata": {"annotation": text}}
        if simple in {"Any", "typing.Any"}:
            return {"metadata": {"annotation": text}}
        if simple in {"None", "NoneType"}:
            return {"type": "null", "metadata": {"annotation": text}}

    if isinstance(node, ast.Subscript):
        return _subscript_to_schema(node, text)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _union_to_schema(_flatten_pep604_union(node), text)

    return {"metadata": {"annotation": text}}


def literal_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Str):
        return node.s
    return None


def schema_with_default(schema: Dict[str, Any], default_node: Optional[ast.AST]) -> Dict[str, Any]:
    if default_node is None:
        return schema
    has_default, value = literal_json_value(default_node)
    if not has_default:
        return schema
    result = dict(schema)
    result["default"] = value
    return result


def literal_json_value(node: ast.AST) -> tuple[bool, Any]:
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError):
        return False, None


def normalize_json_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not schema:
        return {}
    normalized = dict(schema)
    if normalized.get("type") == "object":
        if not isinstance(normalized.get("properties"), dict):
            normalized["properties"] = {}
        normalized["required"] = _required_list(normalized.get("required"))
    return normalized


def build_object_schema(properties: Dict[str, Dict[str, Any]], required: Iterable[str]) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(set(required)),
        "additionalProperties": False,
    }


def _required_list(value: Any) -> List[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sorted(str(item) for item in value)
    return []


def _simple_annotation_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: List[str] = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    return None


def _subscript_to_schema(node: ast.Subscript, text: str) -> Dict[str, Any]:
    base = _simple_annotation_name(node.value) or ""
    short_base = base.split(".")[-1]
    args = _slice_items(node.slice)

    if short_base in {"List", "list", "Sequence", "Iterable", "tuple", "Tuple", "set", "Set"}:
        item_schema = annotation_to_schema(args[0]) if args else {}
        schema: Dict[str, Any] = {"type": "array", "metadata": {"annotation": text}}
        if item_schema:
            schema["items"] = item_schema
        return schema

    if short_base in {"Dict", "dict", "Mapping", "MutableMapping"}:
        value_schema = annotation_to_schema(args[1]) if len(args) > 1 else {}
        schema = {"type": "object", "metadata": {"annotation": text}}
        if value_schema:
            schema["additionalProperties"] = value_schema
        return schema

    if short_base in {"Optional"}:
        inner = annotation_to_schema(args[0]) if args else {}
        return _make_nullable(inner, text)

    if short_base in {"Union"}:
        return _union_to_schema(args, text)

    if short_base in {"Annotated"}:
        schema = annotation_to_schema(args[0]) if args else {}
        schema.setdefault("metadata", {})["annotation"] = text
        return schema

    if short_base in {"Literal"}:
        values = [_literal_enum_value(item) for item in args]
        values = [value for value in values if value is not _MISSING_LITERAL]
        literal_type = _literal_type(values)
        schema = {"enum": values, "metadata": {"annotation": text}}
        if literal_type:
            schema["type"] = literal_type
        return schema

    return {"metadata": {"annotation": text}}


def _slice_items(node: ast.AST) -> Sequence[ast.AST]:
    if isinstance(node, ast.Tuple):
        return list(node.elts)
    return [node]


def _flatten_pep604_union(node: ast.AST) -> List[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _flatten_pep604_union(node.left) + _flatten_pep604_union(node.right)
    return [node]


def _union_to_schema(items: Sequence[ast.AST], text: str) -> Dict[str, Any]:
    schemas = [annotation_to_schema(item) for item in items]
    non_null = [schema for schema in schemas if schema.get("type") != "null"]
    has_null = len(non_null) != len(schemas)
    if has_null and len(non_null) == 1:
        return _make_nullable(non_null[0], text)
    return {"anyOf": schemas, "metadata": {"annotation": text}}


def _make_nullable(schema: Dict[str, Any], text: str) -> Dict[str, Any]:
    result = dict(schema)
    schema_type = result.get("type")
    if isinstance(schema_type, str):
        result["type"] = sorted({schema_type, "null"})
    elif isinstance(schema_type, list):
        result["type"] = sorted(set(schema_type + ["null"]))
    else:
        result["nullable"] = True
    result.setdefault("metadata", {})["annotation"] = text
    return result


def _literal_enum_value(node: ast.AST) -> Any:
    has_value, value = literal_json_value(node)
    return value if has_value else _MISSING_LITERAL


def _literal_type(values: Sequence[Any]) -> Optional[str]:
    if not values:
        return None
    if all(value is None for value in values):
        return "null"
    if all(isinstance(value, str) for value in values):
        return "string"
    if all(isinstance(value, bool) for value in values):
        return "boolean"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "integer"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return "number"
    return None


_SIMPLE_TYPE_MAP = {
    "str": "string",
    "builtins.str": "string",
    "int": "integer",
    "builtins.int": "integer",
    "float": "number",
    "builtins.float": "number",
    "bool": "boolean",
    "builtins.bool": "boolean",
    "dict": "object",
    "list": "array",
}
