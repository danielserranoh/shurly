"""
Phase 8.4 — deploy-backend.yml's parts for MaxMind's GeoLite2 City, whose licence wants the
copy the image carries replaced within 30 days of an update (DEPLOYMENT.md § Geolocation data):
- a weekly scheduled run, which rebuilds main's current commit, and one deploy at a time, so a
  scheduled run and a push can't roll out side by side and land the older commit last;
- MaxMind's account ID and licence key reach the build as BuildKit secrets only: never a build
  argument, an image layer or a line of the (public) log;
- the push build reuses the databases the geolocation step checked, the same run's;
- the geolocation step and the smoke test, their own shell, run with stand-ins for docker, curl
  and sleep: without a GeoLite2 copy when the key is set, nothing is deployed; the smoke test
  still waits for the commit, and now for the run's build too, which is what tells a weekly
  rebuild of the same commit from the image it replaces.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy-backend.yml").read_text())
DOCKERFILE = (ROOT / "dockerfile").read_text()
STEPS = {step.get("name"): step for step in WORKFLOW["jobs"]["deploy"]["steps"]}
SECRETS = (
    "--secret id=maxmind_account_id,env=MAXMIND_ACCOUNT_ID",
    "--secret id=maxmind_license_key,env=MAXMIND_LICENSE_KEY",
)
SHA = "387434fe29c3567e6a18749792ea6273de5f9039"
RUN_ID = "36534428022"


def _builds() -> dict[str, str]:
    """Each step's `docker buildx build …` command, its continuation lines joined."""
    builds = {}
    for name, step in STEPS.items():
        script = step.get("run", "").replace("\\\n", " ")
        for line in script.splitlines():
            if "docker buildx build" in line:
                builds[name] = " ".join(line.split())
    return builds


def test_a_weekly_run_and_one_deploy_at_a_time():
    triggers = WORKFLOW.get("on", WORKFLOW.get(True))  # YAML 1.1 reads a bare `on` as true
    (schedule,) = triggers["schedule"]
    minute, hour, day, month, weekday = schedule["cron"].split()
    assert (day, month) == ("*", "*") and re.fullmatch(r"[0-6]", weekday)
    assert "push" in triggers and triggers["push"]["branches"] == ["main"]

    assert WORKFLOW["concurrency"]["group"]
    assert WORKFLOW["concurrency"]["cancel-in-progress"] is False


def test_the_credentials_are_build_secrets_only():
    builds = _builds()
    assert set(builds) == {"Geolocation data (Phase 8.4)", "Build and push image (multi-arch)"}
    for command in builds.values():
        assert all(secret in command for secret in SECRETS), command
        assert not re.search(r"--build-arg\s+MAXMIND", command), command

    for step in STEPS.values():
        script = step.get("run", "")
        assert not re.search(r"(echo|printf)[^\n]*\$\{?MAXMIND_", script), step["name"]

    # The image mounts them for the fetch alone: no ARG or ENV carries them into a layer.
    assert re.search(
        r"RUN --mount=type=secret,id=maxmind_account_id --mount=type=secret,id=maxmind_license_key",
        DOCKERFILE,
    )
    assert not re.search(r"^(ARG|ENV)\s+MAXMIND", DOCKERFILE, re.MULTILINE)


def test_the_push_build_reuses_what_the_geolocation_step_checked():
    """The same GEOIP_REFRESH in both builds: the push build takes the geoip stage from the
    builder's cache, this run's, rather than fetching again what nobody checked."""
    refresh = {
        name: re.search(r'--build-arg GEOIP_REFRESH="([^"]+)"', command).group(1)
        for name, command in _builds().items()
    }
    assert set(refresh.values()) == {"$GITHUB_RUN_ID"}
    assert re.search(r'ARG GEOIP_REFRESH=""\nRUN --mount=type=secret', DOCKERFILE)


def test_the_image_knows_its_build():
    push = _builds()["Build and push image (multi-arch)"]
    assert '--build-arg BUILD_ID="$GITHUB_RUN_ID"' in push
    assert '--build-arg GIT_SHA="$GITHUB_SHA"' in push
    assert re.search(r"ARG BUILD_ID=unknown\nENV BUILD_ID=\$BUILD_ID", DOCKERFILE)


# ---------------------------------------------------------------------------
# The steps' own shell, with stand-ins
# ---------------------------------------------------------------------------

FAKE_DOCKER = """#!/bin/sh
# docker buildx build … --output type=local,dest=DIR …: writes the files FAKE_GEOIP_FILES names.
dest=""
while [ $# -gt 0 ]; do
  case "$1" in
    --output) dest=$(printf '%s' "$2" | sed -n 's/.*dest=\\([^,]*\\).*/\\1/p'); shift ;;
  esac
  shift
done
mkdir -p "$dest"
for f in $FAKE_GEOIP_FILES; do printf 'mmdb' > "$dest/$f"; done
"""
FAKE_CURL = """#!/bin/sh
printf '%s' "$FAKE_HEALTH"
"""
FAKE_SLEEP = "#!/bin/sh\n"


def _run(step: str, tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    """A step's `run`, as GitHub runs it: bash -eo pipefail, with stand-ins first on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in {"docker": FAKE_DOCKER, "curl": FAKE_CURL, "sleep": FAKE_SLEEP}.items():
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    environment = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_SHA": SHA,
        "GITHUB_RUN_ID": RUN_ID,
        **env,
    }
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", STEPS[step]["run"]],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


GEO = "Geolocation data (Phase 8.4)"
BOTH = "GeoLite2-City.mmdb dbip-country-lite.mmdb"
CREDENTIALS = {"MAXMIND_ACCOUNT_ID": "123456", "MAXMIND_LICENSE_KEY": "marker-licence-key-XYZ"}


def test_geolocation_both_databases(tmp_path):
    result = _run(GEO, tmp_path, FAKE_GEOIP_FILES=BOTH, **CREDENTIALS)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error" not in result.stdout and "::warning" not in result.stdout


def test_geolocation_without_geolite2_when_the_key_is_set_deploys_nothing(tmp_path):
    result = _run(GEO, tmp_path, FAKE_GEOIP_FILES="dbip-country-lite.mmdb", **CREDENTIALS)

    assert result.returncode == 1
    assert "::error title=No GeoLite2 City::" in result.stdout
    assert CREDENTIALS["MAXMIND_LICENSE_KEY"] not in result.stdout + result.stderr


def test_geolocation_without_credentials_warns_and_goes_on(tmp_path):
    result = _run(
        GEO,
        tmp_path,
        FAKE_GEOIP_FILES="dbip-country-lite.mmdb",
        MAXMIND_ACCOUNT_ID="",
        MAXMIND_LICENSE_KEY="",
    )

    assert result.returncode == 0
    assert "::warning title=No MaxMind credentials::" in result.stdout


def test_geolocation_without_the_dbip_fallback_warns(tmp_path):
    result = _run(GEO, tmp_path, FAKE_GEOIP_FILES="GeoLite2-City.mmdb", **CREDENTIALS)

    assert result.returncode == 0
    assert "::warning title=No DB-IP fallback::" in result.stdout


SMOKE = "Smoke test the public host"
needs_jq = pytest.mark.skipif(not shutil.which("jq"), reason="the smoke test reads JSON with jq")


@needs_jq
def test_smoke_passes_once_this_runs_build_serves(tmp_path):
    health = f'{{"status": "ok", "commit": "{SHA}", "build": "{RUN_ID}"}}'

    result = _run(SMOKE, tmp_path, FAKE_HEALTH=health)

    assert result.returncode == 0, result.stdout
    assert "New image is serving" in result.stdout


@needs_jq
@pytest.mark.parametrize(
    "health",
    [
        # The weekly rebuild: the same commit, but last week's image still serving.
        f'{{"status": "ok", "commit": "{SHA}", "build": "36454425222"}}',
        # An image from before /health reported its build.
        f'{{"status": "ok", "commit": "{SHA}"}}',
        # This run's build number can't make up for another commit.
        f'{{"status": "ok", "commit": "{"0" * 40}", "build": "{RUN_ID}"}}',
        "",
    ],
)
def test_smoke_fails_while_another_image_serves(tmp_path, health):
    result = _run(SMOKE, tmp_path, FAKE_HEALTH=health)

    assert result.returncode == 1
    assert "::error::" in result.stdout
