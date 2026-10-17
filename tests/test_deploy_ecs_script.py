"""
`scripts/deploy_ecs.sh` creates the ECS Express service and never updates it (ROADMAP 🔎 R14).

Its update path sent `--primary-container` built from the few variables the script knows, which
replaced the live service's whole environment: every setting added there since (sign in with Google,
the MCP's OAuth, …) would be gone. Now the script stops before building anything once the service
exists. New images go out with the deploy workflow, which changes only the image.

The five secrets live in SSM Parameter Store (`/shurly/production/<NAME>`, SecureString) and reach the
container through its `secrets` field, never its `environment`. The script checks they exist (names
only) before building anything, and never reads a secret from the env or `.env`.

`aws` and `docker` are stubs on PATH that log their calls. The script runs with no AWS configuration
or credentials, so even a stub that failed to load couldn't reach a real account.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_ecs.sh"
ACCOUNT = "123456789012"
EXISTING = f"arn:aws:ecs:eu-south-2:{ACCOUNT}:service/default/shurly-api-5fdb"
SECRETS = [
    "DB_PASSWORD",
    "JWT_SECRET_KEY",
    "GOOGLE_CLIENT_SECRET",
    "MCP_OAUTH_SIGNING_KEY",
    "CLOUDFRONT_ORIGIN_SECRETS",
]
# A stale `.env` or shell may still carry the old plain values: none of them may go anywhere.
LEFTOVER_VALUES = {name: f"leftover-{name.lower()}-0f3a9c" for name in SECRETS}

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="runs a bash script")

AWS_STUB = """#!/bin/bash
echo "aws $*" >> "$CALLS"
case "$1 $2" in
  "sts get-caller-identity") echo "$STUB_ACCOUNT" ;;
  "ecs list-services") echo "$STUB_SERVICE_ARN" ;;
  "ssm get-parameters") echo "$STUB_MISSING_PARAMETERS" ;;
  "ecs create-express-gateway-service")
    while [ $# -gt 0 ]; do
      if [ "$1" = "--primary-container" ]; then printf '%s' "$2" > "$CONTAINER"; fi
      shift
    done ;;
esac
exit 0
"""

DOCKER_STUB = """#!/bin/bash
echo "docker $*" >> "$CALLS"
cat > /dev/null
exit 0
"""


def _stub(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def deploy(tmp_path):
    """Run the script from an empty directory (no .env), `service_arn` being what ECS lists."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    aws = _stub(stubs, "aws", AWS_STUB)
    _stub(stubs, "docker", DOCKER_STUB)
    calls = tmp_path / "calls.log"
    container = tmp_path / "container.json"

    def run(service_arn: str, missing_parameters: str = "", **extra_env: str):
        env = {
            "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "AWS_CONFIG_FILE": str(tmp_path / "no-aws-config"),
            "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "no-aws-credentials"),
            "CALLS": str(calls),
            "CONTAINER": str(container),
            "STUB_ACCOUNT": ACCOUNT,
            "STUB_SERVICE_ARN": service_arn,
            # What `--query InvalidParameters --output text` prints: tab-separated names.
            "STUB_MISSING_PARAMETERS": missing_parameters,
            "DB_HOST": "db.test",
            **LEFTOVER_VALUES,
            **extra_env,
        }
        assert shutil.which("aws", path=env["PATH"]) == str(aws)
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        logged = calls.read_text().splitlines() if calls.exists() else []
        created = json.loads(container.read_text()) if container.exists() else None
        return result, logged, created

    return run


def test_stops_when_the_service_exists(deploy):
    result, calls, _ = deploy(EXISTING)

    assert result.returncode != 0
    assert "already exists" in result.stdout
    # Where to go instead: the deploy workflow for an image, the live service for a setting.
    assert "main" in result.stdout
    assert "DEPLOYMENT.md § Settings" in result.stdout
    # Nothing built, pushed, created or updated: only the account and the service lookup ran.
    assert [call.split()[1:3] for call in calls] == [
        ["sts", "get-caller-identity"],
        ["ecs", "list-services"],
    ]


def _created(calls):
    return [c for c in calls if c.startswith("docker") or "express-gateway-service" in c]


def test_a_failed_lookup_stops_it_too(deploy, tmp_path):
    """If ECS can't be asked, the script can't know the service is missing: it stops."""
    _stub(
        tmp_path / "bin",
        "aws",
        AWS_STUB.replace('"ecs list-services") echo', '"ecs list-services") exit 255; echo'),
    )

    result, calls, _ = deploy("None")

    assert result.returncode != 0
    assert not _created(calls)


@pytest.mark.skipif(shutil.which("jq") is None, reason="the script builds its JSON with jq")
def test_creates_the_service_when_there_is_none(deploy):
    result, calls, container = deploy("None")

    assert result.returncode == 0, result.stdout + result.stderr
    assert any("ecs create-express-gateway-service" in c for c in calls)
    assert not any("update-express-gateway-service" in c for c in calls)
    assert any(c.startswith("docker buildx build") for c in calls)
    env = {e["name"]: e["value"] for e in container["environment"]}
    assert env["CORS_ORIGINS"] == "[]"  # the frontend shares the API's host (DEPLOYMENT.md § CORS)
    assert not any(e["name"] in SECRETS for e in container["environment"])
    assert container["secrets"] == [
        {
            "name": name,
            "valueFrom": f"arn:aws:ssm:eu-south-2:{ACCOUNT}:parameter/shurly/production/{name}",
        }
        for name in SECRETS
    ]
    # No secret value from the env reaches the container or the output.
    sent = json.dumps(container)
    for value in LEFTOVER_VALUES.values():
        assert value not in sent
        assert value not in result.stdout + result.stderr


def test_checks_the_parameters_by_name_only(deploy):
    result, calls, _ = deploy("None")

    lookups = [c for c in calls if c.startswith("aws ssm ")]
    assert len(lookups) == 1
    lookup = lookups[0].split()
    assert lookup[1:3] == ["ssm", "get-parameters"]
    for name in SECRETS:
        assert f"/shurly/production/{name}" in lookup
    assert "InvalidParameters" in lookup
    assert "--with-decryption" not in lookup
    # Checked before anything is built or created.
    first_build = next(i for i, c in enumerate(calls) if c.startswith("docker"))
    assert calls.index(lookups[0]) < first_build


def test_a_missing_parameter_stops_it_before_anything_is_created(deploy):
    missing = "/shurly/production/MCP_OAUTH_SIGNING_KEY"
    result, calls, container = deploy("None", missing_parameters=missing)

    assert result.returncode != 0
    assert missing in result.stdout
    assert "/shurly/production/DB_PASSWORD" not in result.stdout  # only the missing one is named
    assert not _created(calls)
    assert container is None
    for value in LEFTOVER_VALUES.values():
        assert value not in result.stdout + result.stderr


def test_names_every_missing_parameter(deploy):
    missing = ["/shurly/production/DB_PASSWORD", "/shurly/production/GOOGLE_CLIENT_SECRET"]
    result, calls, _ = deploy("None", missing_parameters="\t".join(missing))

    assert result.returncode != 0
    for name in missing:
        assert name in result.stdout
    assert not _created(calls)


def test_a_failed_parameter_lookup_stops_it(deploy, tmp_path):
    """If SSM can't be asked, the script can't know the secrets exist: it stops."""
    _stub(
        tmp_path / "bin",
        "aws",
        AWS_STUB.replace('"ssm get-parameters") echo', '"ssm get-parameters") exit 255; echo'),
    )

    result, calls, _ = deploy("None")

    assert result.returncode != 0
    assert not _created(calls)


@pytest.mark.skipif(shutil.which("jq") is None, reason="the script builds its JSON with jq")
def test_the_prefix_can_be_changed(deploy):
    result, calls, container = deploy("None", SSM_PREFIX="/shurly/staging/")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "/shurly/staging/DB_PASSWORD" in next(c for c in calls if c.startswith("aws ssm "))
    assert {s["valueFrom"] for s in container["secrets"]} == {
        f"arn:aws:ssm:eu-south-2:{ACCOUNT}:parameter/shurly/staging/{name}" for name in SECRETS
    }
