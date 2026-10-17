#!/usr/bin/env python3
"""
Write the database schema diagram (a Mermaid `erDiagram`) into docs/DATABASE_SCHEMA.md,
from the SQLAlchemy models (server/core/models), between its `schema:begin` and
`schema:end` markers.

Run it after changing a model; tests/test_schema_diagram.py fails until you do.

Usage:
    uv run python scripts/generate_schema_diagram.py           # rewrite the doc
    uv run python scripts/generate_schema_diagram.py --check   # exit 1 if it would change
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "DATABASE_SCHEMA.md"
BEGIN = "<!-- schema:begin -->"
END = "<!-- schema:end -->"

sys.path.insert(0, str(ROOT))

from sqlalchemy import (  # noqa: E402
    JSON,
    Boolean,
    DateTime,
    Enum,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    Uuid,
)
from sqlalchemy.schema import Column, Table, UniqueConstraint  # noqa: E402

import server.core.models  # noqa: E402, F401  (registers every model on Base.metadata)
from server.core import Base  # noqa: E402

# Most specific first: Text and Enum are both Strings, so they're checked before it.
_TYPES = [
    (Enum, "enum"),
    (Uuid, "uuid"),
    (Boolean, "bool"),
    (DateTime, "datetime"),
    (JSON, "json"),
    (LargeBinary, "bytes"),
    (Integer, "int"),
    (Text, "text"),
    (String, "string"),
]


def mermaid_type(column: Column) -> str:
    """A short, Mermaid-safe name for the column's type: no spaces, no parentheses."""
    for sql_type, name in _TYPES:
        if isinstance(column.type, sql_type):
            return name
    return re.sub(r"[^a-z0-9_]", "", type(column.type).__name__.lower()) or "unknown"


def is_unique(column: Column) -> bool:
    """The column alone is unique: a single-column primary key, unique flag, constraint or index."""
    table = column.table
    if column.primary_key and len(table.primary_key.columns) == 1:
        return True
    if column.unique:
        return True
    single = [list(c.columns) for c in table.constraints if isinstance(c, UniqueConstraint)]
    single += [list(i.columns) for i in table.indexes if i.unique]
    return any(len(cols) == 1 and cols[0] is column for cols in single)


def _comment(column: Column) -> str:
    parts = []
    if isinstance(column.type, Enum):
        parts.append("/".join(column.type.enums))
    if column.nullable and not column.primary_key:
        parts.append("nullable")
    return ", ".join(parts).replace('"', "'")


def _keys(column: Column) -> str:
    keys = []
    if column.primary_key:
        keys.append("PK")
    if column.foreign_keys:
        keys.append("FK")
    if not column.primary_key and is_unique(column):
        keys.append("UK")
    return ", ".join(keys)


def render_entity(table: Table) -> list[str]:
    lines = [f"    {table.name} {{"]
    for column in table.columns:
        line = f"        {mermaid_type(column)} {column.name}"
        if keys := _keys(column):
            line += f" {keys}"
        if comment := _comment(column):
            line += f' "{comment}"'
        lines.append(line)
    lines.append("    }")
    return lines


def render_relationships(table: Table) -> list[str]:
    """One line per foreign key, parent first: `parent ||--o{ child : "fk_column"`."""
    lines = []
    for column in table.columns:
        for fk in sorted(column.foreign_keys, key=lambda fk: fk.target_fullname):
            parent = fk.column.table.name
            left = "|o" if column.nullable else "||"
            right = "o|" if is_unique(column) else "o{"
            lines.append(f'    {parent} {left}--{right} {table.name} : "{column.name}"')
    return lines


def render_diagram(metadata: MetaData | None = None) -> str:
    """The Mermaid erDiagram for `metadata` (the models' by default): tables by name, columns
    in model order, then the relationships by child table and column."""
    tables = sorted((metadata or Base.metadata).tables.values(), key=lambda t: t.name)
    lines = ["erDiagram"]
    for table in tables:
        lines += render_entity(table)
    for table in tables:
        lines += render_relationships(table)
    return "\n".join(lines) + "\n"


def render_block(metadata: MetaData | None = None) -> str:
    """What goes between the markers, the markers included."""
    return f"{BEGIN}\n```mermaid\n{render_diagram(metadata)}```\n{END}"


def committed_block(text: str) -> str:
    """The block between the markers in `text`, the markers included."""
    start, end = text.find(BEGIN), text.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"{OUTPUT.relative_to(ROOT)} has no {BEGIN} … {END} markers")
    return text[start : end + len(END)]


def render_doc(text: str) -> str:
    """`text` with the block between the markers replaced by the generated one."""
    return text.replace(committed_block(text), render_block(), 1)


def main(argv: list[str]) -> int:
    current = OUTPUT.read_text(encoding="utf-8")
    updated = render_doc(current)
    if "--check" in argv:
        if updated != current:
            print(
                f"{OUTPUT.relative_to(ROOT)} is out of date with the models: "
                "run `uv run python scripts/generate_schema_diagram.py`"
            )
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} is up to date")
        return 0
    OUTPUT.write_text(updated, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
