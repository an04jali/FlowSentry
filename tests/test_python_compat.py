import ast
from pathlib import Path


def test_source_parses_with_declared_python_39_support() -> None:
    for folder in (Path("src"), Path("tests")):
        for path in folder.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path), feature_version=(3, 9))
