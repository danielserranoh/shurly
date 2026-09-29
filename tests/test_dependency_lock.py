"""
Dependencies are pinned by the committed uv.lock (DEPLOYMENT.md § Workflow trigger): CI, the deploy and
the image install exactly it, and new versions arrive only through Dependabot's weekly PR against dev,
which CI runs like any other.

So is what builds them: the image's base images by digest, the setup-uv action by commit, and one uv
version, the lock's, in CI and in the image.
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


def test_dependabot_bumps_uv_the_actions_and_the_images_weekly_against_dev():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    updates = {update["package-ecosystem"]: update for update in config["updates"]}

    assert set(updates) == {"uv", "github-actions", "docker"}
    for update in updates.values():
        assert update["target-branch"] == "dev"
        assert update["schedule"]["interval"] == "weekly"
    for ecosystem in ("uv", "github-actions"):
        (group,) = updates[ecosystem]["groups"].values()
        assert (group["patterns"], group["update-types"]) == (["*"], ["minor", "patch"])
    # The base image's digest, weekly; a new Python, or a new uv, is a change of its own.
    ignored = {
        rule["dependency-name"]: rule.get("update-types") for rule in updates["docker"]["ignore"]
    }
    assert ignored == {
        "ghcr.io/astral-sh/uv": None,
        "python": ["version-update:semver-major", "version-update:semver-minor"],
    }


# ---------------------------------------------------------------------------
# What builds them
# ---------------------------------------------------------------------------

DOCKERFILE = (ROOT / "dockerfile").read_text()
WORKFLOWS = ("test.yml", "deploy-backend.yml")


def _uv_image() -> re.Match:
    found = re.search(
        r"^COPY --from=ghcr\.io/astral-sh/uv:(?P<version>\d+\.\d+\.\d+)@sha256:[0-9a-f]{64} ",
        DOCKERFILE,
        re.MULTILINE,
    )
    assert found, "the image's uv isn't a version pinned by digest"
    return found


def test_every_base_image_is_pinned_by_digest():
    images = re.findall(r"^FROM (?:--platform=\S+ )?(\S+)", DOCKERFILE, re.MULTILINE)

    assert images, "no FROM line"
    unpinned = [
        image
        for image in images
        if image != "scratch" and not re.search(r"@sha256:[0-9a-f]{64}$", image)
    ]
    assert unpinned == []


def test_one_uv_version_in_ci_and_the_image():
    """The lock is read by one uv: the image's version, which CI installs too."""
    version = _uv_image()["version"]
    for name in WORKFLOWS:
        workflow = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
        assert workflow["env"]["UV_VERSION"] == version, name
        steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
        installs = [
            step for step in steps if step.get("uses", "").startswith("astral-sh/setup-uv@")
        ]
        assert installs, name
        assert {step["with"]["version"] for step in installs} == {"${{ env.UV_VERSION }}"}, name


def test_setup_uv_is_pinned_by_commit_and_nothing_pipes_an_installer():
    for name in WORKFLOWS:
        text = (ROOT / ".github" / "workflows" / name).read_text()
        refs = re.findall(r"uses: astral-sh/setup-uv@(\S+)(.*)", text)
        assert refs, name
        for ref, comment in refs:
            assert re.fullmatch(r"[0-9a-f]{40}", ref), (name, ref)
            assert re.match(r"\s+# v\d", comment), (name, "Dependabot needs the version comment")
        assert "astral.sh/uv/install.sh" not in text, name
