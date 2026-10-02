"""
deploy-frontend.yml's build values (DEPLOYMENT.md § Frontend hosting). The host the app shows before
a link's code, PUBLIC_SHORT_DOMAIN, is the repository variable of the same name, and go.griddo.io
while it's unset. The cutover (ROADMAP 8.5) moved it with `gh variable set` and a run of the
workflow by hand, with no release (DEPLOYMENT.md § The cutover).
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy-frontend.yml").read_text())


def _build_env() -> dict[str, str]:
    (build,) = [
        step for step in WORKFLOW["jobs"]["deploy"]["steps"] if step.get("run") == "npm run build"
    ]
    return build["env"]


def test_the_short_domain_is_the_repository_variable_and_go_griddo_io_until_its_set():
    assert _build_env()["PUBLIC_SHORT_DOMAIN"] == (
        "${{ vars.PUBLIC_SHORT_DOMAIN || 'go.griddo.io' }}"
    )


def test_the_variable_is_the_repositorys():
    """No job runs in a GitHub environment, so `vars` is the repository's: what `gh variable set`
    sets by default."""
    assert [name for name, job in WORKFLOW["jobs"].items() if "environment" in job] == []


def test_it_runs_by_hand_too():
    """After the variable changes: `gh workflow run deploy-frontend.yml --ref main`."""
    triggers = WORKFLOW.get("on", WORKFLOW.get(True))  # YAML 1.1 reads a bare `on` as true
    assert "workflow_dispatch" in triggers
