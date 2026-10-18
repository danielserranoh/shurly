"""
The database schema diagram in docs/DATABASE_SCHEMA.md is generated from the models by
scripts/generate_schema_diagram.py; these tests keep the committed copy honest.
"""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "generate_schema_diagram.py"
DOC = ROOT / "docs" / "DATABASE_SCHEMA.md"

ENTITY = re.compile(r"^    ([a-z_][a-z0-9_]*) \{$")
ATTRIBUTE = re.compile(
    r'^        [a-z][a-z0-9_]* [A-Za-z_][A-Za-z0-9_]*( (PK|FK|UK)(, (PK|FK|UK))*)?( "[^"]*")?$'
)
RELATIONSHIP = re.compile(
    r'^    ([a-z_][a-z0-9_]*) (\|\||\|o)--(o\{|o\|) ([a-z_][a-z0-9_]*) : "([a-z_][a-z0-9_]*)"$'
)


@pytest.fixture(scope="module")
def generator():
    spec = importlib.util.spec_from_file_location("generate_schema_diagram", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def diagram(generator):
    """The committed diagram's lines, between ```mermaid and ```."""
    block = generator.committed_block(DOC.read_text(encoding="utf-8")).splitlines()
    assert block[1] == "```mermaid" and block[-2] == "```", "the block must be a ```mermaid fence"
    return block[2:-2]


def test_the_committed_diagram_matches_the_models(generator):
    committed = generator.committed_block(DOC.read_text(encoding="utf-8"))

    assert committed == generator.render_block(), (
        "docs/DATABASE_SCHEMA.md is out of date with the models: "
        "run `uv run python scripts/generate_schema_diagram.py`"
    )


def test_every_table_is_in_the_diagram(generator, diagram):
    entities = {m.group(1) for line in diagram if (m := ENTITY.match(line))}

    assert entities == set(generator.Base.metadata.tables)


def test_the_diagram_parses(generator, diagram):
    assert diagram[0] == "erDiagram"
    entities = {m.group(1) for line in diagram if (m := ENTITY.match(line))}
    depth = 0
    relationships = 0

    for line in diagram[1:]:
        if ENTITY.match(line):
            assert depth == 0, f"an entity opens inside another: {line!r}"
            depth += 1
        elif line == "    }":
            assert depth == 1, "a closing brace without an entity"
            depth -= 1
        elif depth == 1:
            assert ATTRIBUTE.match(line), f"not a Mermaid attribute: {line!r}"
        else:
            match = RELATIONSHIP.match(line)
            assert match, f"not a Mermaid relationship: {line!r}"
            parent, child = match.group(1), match.group(4)
            assert {parent, child} <= entities, f"a relationship to an unknown table: {line!r}"
            relationships += 1

    assert depth == 0, "an entity is never closed"
    foreign_keys = sum(
        len(column.foreign_keys)
        for table in generator.Base.metadata.tables.values()
        for column in table.columns
    )
    assert relationships == foreign_keys


def test_cardinality_follows_the_foreign_key(diagram):
    relationships = {
        (m.group(1), m.group(4), m.group(5)): m.group(2) + "--" + m.group(3)
        for line in diagram
        if (m := RELATIONSHIP.match(line))
    }

    assert relationships[("urls", "visits", "url_id")] == "||--o{"
    assert relationships[("domains", "urls", "domain_id")] == "|o--o{"
    # user_profiles.user_id is its primary key: one profile per user at most.
    assert relationships[("users", "user_profiles", "user_id")] == "||--o|"


def test_check_mode_reports_a_stale_doc(generator, tmp_path, monkeypatch, capsys):
    stale = tmp_path / "DATABASE_SCHEMA.md"
    stale.write_text(
        f"# Schema\n\n{generator.BEGIN}\n```mermaid\nerDiagram\n```\n{generator.END}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(generator, "OUTPUT", stale)
    monkeypatch.setattr(generator, "ROOT", tmp_path)

    assert generator.main(["--check"]) == 1
    assert "generate_schema_diagram.py" in capsys.readouterr().out
    assert generator.main([]) == 0
    assert generator.main(["--check"]) == 0
    assert stale.read_text(encoding="utf-8").startswith("# Schema\n\n")
