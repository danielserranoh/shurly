"""
ROADMAP 7.1 — docs/ENVIRONMENT.md lists every environment variable Shurly reads, with its
default and what it does: the backend's settings (server/core/config.py), what the backend,
its tools and its tests read directly, and what the frontend's build reads. A setting's
default must match its row. So a new variable can't ship undocumented, and a changed default
can't leave the reference behind.
"""

import ast
import json
import re
from pathlib import Path

from pydantic import SecretStr

from server.core.config import Settings

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "ENVIRONMENT.md"
ROW = re.compile(r"^\| `(?P<name>[A-Z][A-Z0-9_]*)` \| (?P<default>[^|]+) \| (?P<meaning>[^|]+) \|$")
BACKEND_SOURCES = [
    *sorted((ROOT / "server").rglob("*.py")),
    *sorted((ROOT / "mcp_server").rglob("*.py")),
    *sorted((ROOT / "scripts").rglob("*.py")),
    ROOT / "main.py",
    ROOT / "tests" / "conftest.py",
]
FRONTEND_SOURCES = [
    *(path for path in sorted((ROOT / "frontend" / "src").rglob("*")) if path.is_file()),
    *sorted((ROOT / "frontend" / "scripts").rglob("*.mjs")),
    ROOT / "frontend" / "astro.config.mjs",
]
FRONTEND_READ = re.compile(r"\b(?:import\.meta\.env|process\.env|env)\.(PUBLIC_[A-Z0-9_]+)")


def _rows() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in DOC.read_text().splitlines():
        row = ROW.match(line)
        if row:
            assert row["name"] not in rows, f"two rows for {row['name']}"
            rows[row["name"]] = {"default": row["default"].strip(), "meaning": row["meaning"]}
    return rows


def _rendered(default) -> str:
    """A default as its row shows it."""
    if isinstance(default, SecretStr):
        return "(empty)" if not default.get_secret_value() else "(set in code)"
    if isinstance(default, bool):
        return f"`{str(default).lower()}`"
    if isinstance(default, int | float):
        return f"`{default}`"
    if isinstance(default, str):
        return f"`{default}`" if default else "(empty)"
    if isinstance(default, list):
        return f"`{json.dumps(default)}`" if default else "(empty)"
    return "(see `config.py`)"


def _read_by_the_backend() -> set[str]:
    """`os.getenv("X")`, `os.environ.get("X")` and `os.environ["X"]`, wherever they are."""
    names = set()
    for path in BACKEND_SOURCES:
        for node in ast.walk(ast.parse(path.read_text())):
            key = None
            if isinstance(node, ast.Call) and node.args:
                func = node.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                on_environ = (
                    isinstance(func, ast.Attribute) and ast.unparse(func.value) == "os.environ"
                )
                if called == "getenv" or (called == "get" and on_environ):
                    key = node.args[0]
            elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                names.add(key.value)
    return names


def _read_by_the_frontend() -> set[str]:
    return {
        name
        for path in FRONTEND_SOURCES
        for name in FRONTEND_READ.findall(path.read_text(errors="ignore"))
    }


def test_every_setting_has_its_row_and_default():
    rows = _rows()
    for field, info in Settings.model_fields.items():
        name = field.upper()
        assert name in rows, f"{name} has no row in docs/ENVIRONMENT.md"
        assert rows[name]["default"] == _rendered(info.default), f"{name}'s default"


def test_every_variable_read_elsewhere_has_a_row():
    rows = _rows()
    for name in sorted(_read_by_the_backend() | _read_by_the_frontend()):
        assert name in rows, f"{name} is read but has no row in docs/ENVIRONMENT.md"


def test_every_row_names_a_variable():
    known = {field.upper() for field in Settings.model_fields}
    known |= _read_by_the_backend() | _read_by_the_frontend()
    stale = sorted(set(_rows()) - known)
    assert not stale, f"rows for variables nothing reads: {stale}"


def test_the_scans_find_what_they_should():
    """If these empty, the scans have gone blind, and the tests above would pass on nothing."""
    assert {
        "GIT_SHA",
        "MCP_DISABLE_MOUNT",
        "SHLINK_API_KEY",
        "TEST_DATABASE_URL",
    } <= _read_by_the_backend()
    assert {"PUBLIC_API_URL", "PUBLIC_MCP_URL", "PUBLIC_SITE_URL"} <= _read_by_the_frontend()
