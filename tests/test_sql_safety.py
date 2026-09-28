"""
Phase 6.3 — no SQL built from strings.

The API reaches the database through the ORM and SQLAlchemy Core, which bind every value as a
parameter. This test reads the backend's source (server/, mcp_server/, main.py) and fails on
the ways around that:

- `text()`, `exec_driver_sql()` or `literal_column()` given anything but a string literal: an
  f-string, `%`, `.format`, `+`, a variable. Values go in as `:name` parameters instead.
- A LIKE helper on a column (`contains`, `startswith`, `endswith`, their `i…` forms, `like`,
  `ilike`) given a variable without `autoescape=True` (or an explicit `escape=`): `%` and `_`
  in the input would then be wildcards.

Migrations are left out: they run once, on constants, never on input. An exception goes in
ALLOWED as (file, a snippet of its line, why it's safe); an entry that no longer matches
anything fails, so the list stays true.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [
    *sorted((ROOT / "server").rglob("*.py")),
    *sorted((ROOT / "mcp_server").rglob("*.py")),
    ROOT / "main.py",
]
SKIP = (ROOT / "server" / "migrations",)

RAW_SQL = {"text", "exec_driver_sql", "literal_column"}
LIKE = {
    "contains",
    "startswith",
    "endswith",
    "icontains",
    "istartswith",
    "iendswith",
    "like",
    "ilike",
    "notlike",
    "notilike",
}
# No `str` method has these names, so the receiver is a column whatever it looks like.
SQL_ONLY_LIKE = LIKE - {"contains", "startswith", "endswith"}

ALLOWED: list[tuple[str, str, str]] = []


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_string_literal(node: ast.expr) -> bool:
    # Implicitly concatenated literals ("a" "b") are one Constant too.
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _looks_like_column(node: ast.expr) -> bool:
    """`Model.column` (a capitalised root, like `Tag.name`) or `func.lower(Model.column)`."""
    root = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if isinstance(root, ast.Name):
        return root.id[:1].isupper()
    return (
        isinstance(root, ast.Call)
        and isinstance(root.func, ast.Attribute)
        and isinstance(root.func.value, ast.Name)
        and root.func.value.id == "func"
    )


def findings(source: str) -> list[tuple[int, str]]:
    """(line, what) for every call in `source` that builds SQL, or a LIKE pattern, from input."""
    problems = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node.func)
        if name in RAW_SQL:
            if not node.args or not _is_string_literal(node.args[0]):
                problems.append((node.lineno, f"{name}() on something other than a string literal"))
        elif name in LIKE and isinstance(node.func, ast.Attribute):
            if name not in SQL_ONLY_LIKE and not _looks_like_column(node.func.value):
                continue  # a str method: value.startswith(prefix)
            escaped = any(keyword.arg in ("autoescape", "escape") for keyword in node.keywords)
            if node.args and not _is_string_literal(node.args[0]) and not escaped:
                problems.append((node.lineno, f".{name}() on input without autoescape=True"))
    return problems


def test_no_sql_built_from_strings():
    problems = []
    unused = list(ALLOWED)
    for path in SOURCES:
        if any(skipped in path.parents for skipped in SKIP):
            continue
        relative = path.relative_to(ROOT).as_posix()
        source = path.read_text()
        lines = source.splitlines()
        for lineno, what in findings(source):
            line = lines[lineno - 1].strip()
            entry = next((a for a in ALLOWED if a[0] == relative and a[1] in line), None)
            if entry:
                if entry in unused:
                    unused.remove(entry)
                continue
            problems.append(f"{relative}:{lineno}  {what}: {line}")
    problems += [f"allowlisted but gone: {file}  {snippet}" for file, snippet, _ in unused]
    assert not problems, (
        "Bind values as parameters (the ORM, or text() with :name and a dict), and give LIKE "
        "helpers autoescape=True:\n" + "\n".join(problems)
    )


@pytest.mark.parametrize(
    "code",
    [
        """db.execute(text(f"SELECT * FROM urls WHERE short_code = '{code}'"))""",
        """db.execute(text("SELECT * FROM urls WHERE short_code = '" + code + "'"))""",
        """db.execute(text("SELECT * FROM urls WHERE id = %s" % url_id))""",
        """db.execute(text("SELECT * FROM urls WHERE id = {}".format(url_id)))""",
        "db.execute(text(query))",
        "connection.exec_driver_sql(query)",
        "select(literal_column(name))",
        "query.filter(Tag.name.startswith(search))",
        "query.filter(URL.title.icontains(q))",
        "query.filter(func.lower(URL.title).contains(q))",
        "query.filter(URL.title.ilike(pattern))",
    ],
)
def test_the_scan_catches(code):
    assert findings(code)


@pytest.mark.parametrize(
    "code",
    [
        """db.execute(text("SELECT 1"))""",
        """db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})""",
        "query.filter(Tag.name.startswith(search, autoescape=True))",
        "query.filter(URL.title.icontains(q, autoescape=True))",
        """query.filter(URL.title.ilike(pattern, escape="\\\\"))""",
        """query.filter(URL.short_code.startswith("abc"))""",
        "value.startswith(prefix)",
        "request.url.path.endswith(suffix)",
    ],
)
def test_the_scan_lets_through(code):
    assert not findings(code)
