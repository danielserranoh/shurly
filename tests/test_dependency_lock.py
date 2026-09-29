"""
Dependencies are pinned by the committed uv.lock (DEPLOYMENT.md § Workflow trigger): CI, the deploy and
the image install exactly it, and new versions arrive only through Dependabot's weekly PR against dev,
which CI runs like any other.
"""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parents[1]


def test_the_lock_is_committed():
    assert (ROOT / "uv.lock").is_file()
    ignored = [line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()]
    assert "uv.lock" not in ignored and "*.lock" not in ignored


def test_ci_and_the_deploy_install_exactly_the_lock():
    """`--locked` also fails a PR that changed pyproject.toml without `uv lock`."""
    syncs = [
        (workflow.name, line.strip())
        for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        for line in workflow.read_text().splitlines()
        if re.match(r"\s*(run:\s*)?uv sync\b", line)
    ]

    assert {name for name, _ in syncs} >= {"test.yml", "deploy-backend.yml"}
    assert [sync for sync in syncs if "--locked" not in sync[1]] == []


def test_the_image_installs_the_lock():
    dockerfile = (ROOT / "dockerfile").read_text()

    assert re.search(r"^COPY pyproject\.toml uv\.lock ", dockerfile, re.MULTILINE)
    assert re.search(r"^RUN uv sync [^\n]*--frozen", dockerfile, re.MULTILINE)
    dockerignore = (ROOT / ".dockerignore").read_text()
    assert not re.search(r"^uv\.lock$", dockerignore, re.MULTILINE)


def test_dependabot_bumps_uv_and_the_actions_weekly_against_dev():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    updates = {update["package-ecosystem"]: update for update in config["updates"]}

    assert set(updates) == {"uv", "github-actions"}
    for update in updates.values():
        assert update["target-branch"] == "dev"
        assert update["schedule"]["interval"] == "weekly"
        (group,) = update["groups"].values()
        assert (group["patterns"], group["update-types"]) == (["*"], ["minor", "patch"])
