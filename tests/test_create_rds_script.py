"""
`scripts/create_rds.sh` writes the master password it generates straight to SSM Parameter Store and
never prints it.

It used to print a fresh password and say to save it in Secrets Manager, even on a re-run where the
instance already existed and the password went nowhere. Now, only when it creates the instance, it
stores the password as the SecureString `/shurly/production/DB_PASSWORD` (`SSM_PREFIX`), overwriting,
through a 0600 file passed with `--cli-input-json`, the way DEPLOYMENT.md § Secrets' `put_secret` does.
An existing instance means no password and no write.

`aws` is a stub on PATH that logs its calls and keeps a copy of the parameter file it's given. The
script runs with no AWS configuration or credentials, so even a stub that failed to load couldn't
reach a real account.
"""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_rds.sh"
ENDPOINT = "shurly-db.abc123.eu-south-2.rds.amazonaws.com"

pytestmark = [
    pytest.mark.skipif(shutil.which("bash") is None, reason="runs a bash script"),
    pytest.mark.skipif(
        shutil.which("jq") is None, reason="the script writes the parameter with jq"
    ),
    pytest.mark.skipif(shutil.which("openssl") is None, reason="the script generates with openssl"),
]

AWS_STUB = r"""#!/bin/bash
echo "aws $*" >> "$CALLS"
case "$1 $2" in
  "ec2 describe-vpcs")
    case "$*" in *CidrBlock*) echo "172.31.0.0/16" ;; *) echo "vpc-0abc" ;; esac ;;
  "ec2 describe-security-groups") echo "sg-0abc" ;;
  "ec2 authorize-security-group-ingress") ;;
  "rds describe-db-subnet-groups") ;;
  "rds describe-db-instances")
    case "$*" in
      *--query*) echo "$STUB_ENDPOINT" ;;
      *) [ "$STUB_INSTANCE_EXISTS" = true ] || exit 254 ;;
    esac ;;
  "rds wait") ;;
  "ssm put-parameter")
    [ "$STUB_PUT_FAILS" = true ] && exit 255
    while [ $# -gt 0 ]; do
      if [ "$1" = "--cli-input-json" ]; then
        file="${2#file://}"
        cp "$file" "$PARAMETER"
        { stat -c %a "$file" 2>/dev/null || stat -f %Lp "$file"; } > "$PARAMETER_MODE"
      fi
      shift
    done
    echo 3 ;;
  "rds create-db-instance")
    while [ $# -gt 0 ]; do
      if [ "$1" = "--master-user-password" ]; then printf '%s' "$2" > "$MASTER_PASSWORD"; fi
      shift
    done ;;
  *) echo "unexpected aws call: $*" >&2; exit 99 ;;
esac
exit 0
"""


@pytest.fixture
def create_rds(tmp_path):
    """Run the script from an empty directory with the `aws` stub; returns what it saw."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    aws = stubs / "aws"
    aws.write_text(AWS_STUB)
    aws.chmod(aws.stat().st_mode | stat.S_IXUSR)
    temp = tmp_path / "tmp"
    temp.mkdir()
    files = {
        "calls": tmp_path / "calls.log",
        "parameter": tmp_path / "parameter.json",
        "mode": tmp_path / "parameter.mode",
        "master": tmp_path / "master-password",
    }

    def run(instance_exists: bool = False, put_fails: bool = False, **extra_env: str):
        env = {
            "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "TMPDIR": str(temp),
            "AWS_CONFIG_FILE": str(tmp_path / "no-aws-config"),
            "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "no-aws-credentials"),
            "CALLS": str(files["calls"]),
            "PARAMETER": str(files["parameter"]),
            "PARAMETER_MODE": str(files["mode"]),
            "MASTER_PASSWORD": str(files["master"]),
            "STUB_ENDPOINT": ENDPOINT,
            "STUB_INSTANCE_EXISTS": "true" if instance_exists else "false",
            "STUB_PUT_FAILS": "true" if put_fails else "false",
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
        seen = {
            "calls": files["calls"].read_text().splitlines() if files["calls"].exists() else [],
            "parameter": (
                json.loads(files["parameter"].read_text()) if files["parameter"].exists() else None
            ),
            "mode": files["mode"].read_text().strip() if files["mode"].exists() else None,
            "master": files["master"].read_text() if files["master"].exists() else None,
            "leftovers": sorted(p.name for p in temp.rglob("*")),
        }
        return result, seen

    return run


def _commands(calls):
    return [call.split()[1:3] for call in calls]


def test_the_password_goes_to_ssm_as_a_secure_string(create_rds):
    result, seen = create_rds()

    assert result.returncode == 0, result.stdout + result.stderr
    parameter = seen["parameter"]
    assert parameter["Name"] == "/shurly/production/DB_PASSWORD"
    assert parameter["Type"] == "SecureString"
    assert parameter["Overwrite"] is True
    password = parameter["Value"]
    assert re.fullmatch(r"[A-Za-z0-9]{32}", password)
    # Through a file only the user can read, gone once the script ends.
    assert seen["mode"] == "600"
    assert seen["leftovers"] == []


def test_it_is_the_password_the_instance_is_created_with(create_rds):
    result, seen = create_rds()

    assert result.returncode == 0, result.stdout + result.stderr
    assert seen["master"] == seen["parameter"]["Value"]
    # Stored before the instance exists: a failed write never leaves an instance nobody can open.
    commands = _commands(seen["calls"])
    assert commands.index(["ssm", "put-parameter"]) < commands.index(["rds", "create-db-instance"])


def test_the_password_is_never_printed(create_rds):
    result, seen = create_rds()

    assert result.returncode == 0, result.stdout + result.stderr
    password = seen["parameter"]["Value"]
    assert password not in result.stdout
    assert password not in result.stderr
    assert "/shurly/production/DB_PASSWORD" in result.stdout  # where it went, instead
    assert "Secrets Manager" not in result.stdout


def test_the_password_reaches_only_put_parameter_and_create(create_rds):
    result, seen = create_rds()

    assert result.returncode == 0, result.stdout + result.stderr
    password = seen["parameter"]["Value"]
    put = next(c for c in seen["calls"] if c.startswith("aws ssm put-parameter"))
    assert password not in put  # its value is in the file, not on the command line
    assert "--cli-input-json file://" in put
    holding = [c for c in seen["calls"] if password in c]
    assert [c.split()[1:3] for c in holding] == [["rds", "create-db-instance"]]


def test_an_existing_instance_means_no_password_and_no_write(create_rds):
    result, seen = create_rds(instance_exists=True)

    assert result.returncode == 0, result.stdout + result.stderr
    commands = _commands(seen["calls"])
    assert ["ssm", "put-parameter"] not in commands
    assert ["rds", "create-db-instance"] not in commands
    assert seen["parameter"] is None
    assert "already exists" in result.stdout
    assert "nothing written to SSM" in result.stdout


def test_a_failed_write_stops_it_before_the_instance(create_rds):
    result, seen = create_rds(put_fails=True)

    assert result.returncode != 0
    assert ["rds", "create-db-instance"] not in _commands(seen["calls"])
    assert seen["leftovers"] == []  # the parameter file is removed on the way out too


def test_the_prefix_can_be_changed(create_rds):
    result, seen = create_rds(SSM_PREFIX="/shurly/staging/")

    assert result.returncode == 0, result.stdout + result.stderr
    assert seen["parameter"]["Name"] == "/shurly/staging/DB_PASSWORD"
