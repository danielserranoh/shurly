"""
Phase 6.1 — the end-to-end API (tests/e2e/app.py) signs anyone in through a fake
Google, so it stays out of what's deployed: it starts only with E2E=1 on a local
database, nothing outside tests/ imports it, and the image never copies tests/.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.e2e.guard import refuse_unless_local

ROOT = Path(__file__).resolve().parent.parent


def copied_sources(dockerfile: str) -> list[str]:
    """The build-context paths a Dockerfile's COPY and ADD take (not those `--from` a stage)."""
    sources: list[str] = []
    for line in re.sub(r"\\\n", " ", dockerfile).splitlines():
        words = line.split()
        if not words or words[0].upper() not in {"COPY", "ADD"}:
            continue
        flags = [w for w in words[1:] if w.startswith("--")]
        if any(flag.startswith("--from") for flag in flags):
            continue
        args = [w for w in words[1:] if not w.startswith("--")]
        if args and args[0].startswith("["):
            args = json.loads(" ".join(args))
        sources += args[:-1]
    return sources


def takes_tests(source: str, dockerignore: str) -> bool:
    """Whether copying `source` brings tests/ into the image."""
    path = source.strip().removeprefix("./").rstrip("/")
    if path in {"", ".", "*"}:  # the whole context: only .dockerignore keeps tests/ out
        ignored = {line.strip().removeprefix("/").rstrip("/") for line in dockerignore.splitlines()}
        return "tests" not in ignored
    return path == "tests" or path.startswith("tests/")


class TestTheImageNeverCopiesTests:
    def test_the_dockerfile_copies_nothing_from_tests(self):
        dockerfile = (ROOT / "dockerfile").read_text()
        dockerignore = (ROOT / ".dockerignore").read_text()
        sources = copied_sources(dockerfile)
        assert "main.py" in sources  # the parser does find the COPY lines
        assert [s for s in sources if takes_tests(s, dockerignore)] == []

    def test_and_the_dockerignore_leaves_tests_out_as_well(self):
        lines = (ROOT / ".dockerignore").read_text().splitlines()
        assert "tests/" in [line.strip() for line in lines]

    def test_the_check_catches_a_copy_of_tests(self):
        dockerfile = (
            "FROM python:3.11-slim\nCOPY server ./server\nCOPY tests/e2e \\\n  ./tests/e2e\n"
        )
        assert [s for s in copied_sources(dockerfile) if takes_tests(s, "")] == ["tests/e2e"]

    def test_and_a_copy_of_the_whole_context_unless_the_dockerignore_drops_tests(self):
        sources = copied_sources("COPY --chown=app:app . /app\n")
        assert sources == ["."]
        assert takes_tests(".", "frontend/\n")
        assert not takes_tests(".", "frontend/\ntests/\n")

    def test_it_reads_the_json_form_and_skips_other_stages(self):
        dockerfile = 'COPY ["main.py", "./"]\nCOPY --from=builder /app/tests /app/tests\n'
        assert copied_sources(dockerfile) == ["main.py"]


class TestTheWrapperStartsOnlyOnPurpose:
    LOCAL = {"E2E": "1", "DB_HOST": "localhost"}

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
    def test_it_starts_with_e2e_and_a_local_database(self, host):
        refuse_unless_local({"E2E": "1", "DB_HOST": host})

    @pytest.mark.parametrize("value", [None, "", "0", "true"])
    def test_it_refuses_without_e2e_1(self, value):
        environ = {"DB_HOST": "localhost"} if value is None else {**self.LOCAL, "E2E": value}
        with pytest.raises(SystemExit, match="E2E=1"):
            refuse_unless_local(environ)

    @pytest.mark.parametrize("host", [None, "", "db", "shurly.abc123.eu-west-1.rds.amazonaws.com"])
    def test_it_refuses_a_database_that_isnt_local(self, host):
        environ = {"E2E": "1"} if host is None else {"E2E": "1", "DB_HOST": host}
        with pytest.raises(SystemExit, match="local"):
            refuse_unless_local(environ)

    def test_importing_it_refuses_before_the_app_is_built(self):
        env = {k: v for k, v in os.environ.items() if k not in {"E2E", "DB_HOST"}}
        run = subprocess.run(
            [sys.executable, "-c", "import tests.e2e.app"],
            cwd=ROOT,
            env={**env, "DB_HOST": "localhost"},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert run.returncode != 0
        assert "E2E=1" in run.stderr
        assert "Traceback" not in run.stderr  # refused, not crashed


def test_nothing_outside_tests_imports_it():
    code = [
        ROOT / "main.py",
        *(ROOT / "server").rglob("*.py"),
        *(ROOT / "mcp_server").rglob("*.py"),
    ]
    importing = [
        str(path.relative_to(ROOT))
        for path in code
        if re.search(r"^\s*(from|import)\s+tests\b", path.read_text(), re.MULTILINE)
    ]
    assert importing == []
