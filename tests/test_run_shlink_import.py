"""
`scripts/run_shlink_import.sh` (ROADMAP 8.4, decision B): the Shlink import as a one-off ECS task,
from the live service's image, environment and network. Run here against a fake `aws` that
answers as AWS would and records every call, so what it would do in AWS is checked without AWS.

- A dry run unless --for-real, which needs the owner's email typed back.
- The task definition is the live one's app container, plus an AWS CLI container that copies the
  files from the bucket with the import's own task role; both log to the service's group.
- The service's secrets, in the live environment, never reach the terminal.
- The task definition and the local files are deleted at the end, whatever happened.
"""

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_shlink_import.sh"
SECRETS = ("s3cr3t-db-password", "s3cr3t-jwt-key")
SERVICE_TD = "arn:aws:ecs:eu-south-2:123456789012:task-definition/shurly-api-5fdb:7"
NEW_TD = "arn:aws:ecs:eu-south-2:123456789012:task-definition/shurly-shlink-import:1"
TASK = "arn:aws:ecs:eu-south-2:123456789012:task/default/abc123"
NETWORK = {
    "awsvpcConfiguration": {
        "subnets": ["subnet-1", "subnet-2"],
        "securityGroups": ["sg-1"],
        "assignPublicIp": "ENABLED",
    }
}
LIVE = {
    "executionRoleArn": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole",
    "runtimePlatform": {"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"},
    "containerDefinitions": [
        {
            "name": "Main",
            "image": "123456789012.dkr.ecr.eu-south-2.amazonaws.com/shurly-api:abc",
            "environment": [
                {"name": "DB_HOST", "value": "shurly.db.internal"},
                {"name": "DB_PASSWORD", "value": SECRETS[0]},
                {"name": "JWT_SECRET_KEY", "value": SECRETS[1]},
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/aws/ecs/default/shurly-api-5fdb",
                    "awslogs-region": "eu-south-2",
                    "awslogs-stream-prefix": "ecs",
                },
            },
        }
    ],
}

FAKE_AWS = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, shutil, sys
    from pathlib import Path

    state = Path(os.environ["FAKE_AWS_STATE"])
    args = sys.argv[1:]
    while args and args[0] in ("--profile", "--region"):
        args = args[2:]
    with open(state / "calls.jsonl", "a") as log:
        log.write(json.dumps(args) + "\\n")

    def option(name):
        return args[args.index(name) + 1] if name in args else None

    live = json.loads(os.environ["FAKE_LIVE"])
    command = args[:2]
    if command == ["s3", "ls"]:
        missing = os.environ.get("FAKE_AWS_MISSING", "")
        if missing and args[2].endswith("/" + missing):
            sys.exit(1)
        print("2026-09-29 10:00:00    1024 " + args[2].rsplit("/", 1)[1])
    elif command == ["sts", "get-caller-identity"]:
        print("123456789012")
    elif command == ["ecs", "list-services"]:
        print("arn:aws:ecs:eu-south-2:123456789012:service/default/shurly-api-5fdb")
    elif command == ["ecs", "describe-services"]:
        print(json.dumps({"taskDefinition": os.environ["FAKE_SERVICE_TD"],
                          "networkConfiguration": json.loads(os.environ["FAKE_NETWORK"])}))
    elif command == ["ecs", "describe-task-definition"]:
        print(json.dumps(live))
    elif command == ["ecs", "register-task-definition"]:
        source = option("--cli-input-json").removeprefix("file://")
        shutil.copy(source, state / "registered.json")
        (state / "registered-from").write_text(source)
        print(os.environ["FAKE_NEW_TD"])
    elif command == ["ecs", "run-task"]:
        (state / "run-task.json").write_text(json.dumps({
            "network": json.loads(option("--network-configuration")),
            "overrides": json.loads(option("--overrides")),
            "task_definition": option("--task-definition"),
        }))
        print(os.environ["FAKE_TASK"])
    elif command == ["ecs", "describe-tasks"]:
        query = option("--query")
        print("STOPPED" if query.endswith("lastStatus") else os.environ.get("FAKE_IMPORT_EXIT", "0"))
    elif command == ["logs", "tail"]:
        print("[" + option("--log-stream-names") + "] Imported 3 links")
    elif command in (["ecs", "deregister-task-definition"], ["ecs", "delete-task-definitions"]):
        print("{}")
    else:
        print("unexpected call: " + " ".join(args), file=sys.stderr)
        sys.exit(99)
    """
)

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="the script needs jq")


@pytest.fixture
def aws(tmp_path) -> Path:
    """A fake `aws` first on PATH, and the directory where it records what it was asked."""
    bin_dir, state = tmp_path / "bin", tmp_path / "state"
    bin_dir.mkdir()
    state.mkdir()
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return state


def _run(
    state: Path, *args: str, stdin: str = "", script: Path = SCRIPT, **extra
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "PATH": f"{state.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_AWS_STATE": str(state),
        "FAKE_LIVE": json.dumps(LIVE),
        "FAKE_SERVICE_TD": SERVICE_TD,
        "FAKE_NETWORK": json.dumps(NETWORK),
        "FAKE_NEW_TD": NEW_TD,
        "FAKE_TASK": TASK,
        **extra,
    }
    return subprocess.run(
        ["bash", str(script), *args],
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )


ARGS = ("--bucket", "shurly-imports", "--prefix", "shlink/2026-09-29/", "--as", "owner@griddo.io")


def _calls(state: Path) -> list[list[str]]:
    return [json.loads(line) for line in (state / "calls.jsonl").read_text().splitlines()]


def _command(state: Path) -> list[str]:
    run = json.loads((state / "run-task.json").read_text())
    (override,) = run["overrides"]["containerOverrides"]
    assert override["name"] == "import"
    return override["command"]


def test_a_dry_run_by_default(aws):
    result = _run(aws, *ARGS)

    assert result.returncode == 0, result.stderr
    assert _command(aws) == [
        "python",
        "-m",
        "server.tools.shlink",
        "import",
        "/import/snapshot.json",
        "/import/review.csv",
        "--as",
        "owner@griddo.io",
        "--dry-run",
    ]
    assert "dry run" in result.stdout


def test_its_visits_and_other_file_names(aws):
    _run(aws, *ARGS, "--visits", "--snapshot", "go.snapshot.json", "--review", "go.review.csv")

    assert _command(aws)[4:6] == ["/import/go.snapshot.json", "/import/go.review.csv"]
    assert _command(aws)[-2:] == ["--visits", "--dry-run"]


def test_the_task_is_the_live_services_plus_one_that_fetches_the_files(aws):
    _run(aws, *ARGS)

    registered = json.loads((aws / "registered.json").read_text())
    fetch, imports = registered["containerDefinitions"]
    live = LIVE["containerDefinitions"][0]
    logs = {**live["logConfiguration"]["options"], "awslogs-stream-prefix": "shlink-import"}
    assert (registered["family"], registered["taskRoleArn"]) == (
        "shurly-shlink-import",
        "arn:aws:iam::123456789012:role/shurly-shlink-import",
    )
    assert registered["executionRoleArn"] == LIVE["executionRoleArn"]
    assert registered["runtimePlatform"] == LIVE["runtimePlatform"]
    assert (fetch["name"], fetch["essential"], fetch["image"]) == (
        "fetch",
        False,
        "public.ecr.aws/aws-cli/aws-cli:2.17.52",
    )
    assert fetch["command"] == [
        "s3",
        "cp",
        "s3://shurly-imports/shlink/2026-09-29/",
        "/import/",
        "--recursive",
        "--only-show-errors",
    ]
    assert (imports["image"], imports["environment"]) == (live["image"], live["environment"])
    assert imports["dependsOn"] == [{"containerName": "fetch", "condition": "SUCCESS"}]
    assert imports["mountPoints"] == [
        {"sourceVolume": "import", "containerPath": "/import", "readOnly": True}
    ]
    assert fetch["logConfiguration"]["options"] == imports["logConfiguration"]["options"] == logs


def test_it_runs_in_the_services_network(aws):
    _run(aws, *ARGS)

    run = json.loads((aws / "run-task.json").read_text())
    assert (run["network"], run["task_definition"]) == (NETWORK, NEW_TD)


def test_the_services_secrets_never_reach_the_terminal(aws):
    result = _run(aws, *ARGS)

    assert not [secret for secret in SECRETS if secret in result.stdout + result.stderr]


def test_the_task_definition_and_the_local_files_are_deleted(aws):
    _run(aws, *ARGS)

    calls = _calls(aws)
    assert ["ecs", "deregister-task-definition", "--task-definition", NEW_TD] in calls
    assert ["ecs", "delete-task-definitions", "--task-definitions", NEW_TD] in calls
    assert not Path((aws / "registered-from").read_text()).exists()


def test_a_failed_import_fails_the_script_and_still_cleans_up(aws):
    result = _run(aws, *ARGS, FAKE_IMPORT_EXIT="1")

    assert result.returncode == 1
    assert "exited with 1" in result.stderr
    assert ["ecs", "delete-task-definitions", "--task-definitions", NEW_TD] in _calls(aws)


def test_its_output_is_shown_from_cloudwatch(aws):
    result = _run(aws, *ARGS)

    assert "[shlink-import/import/abc123] Imported 3 links" in result.stdout
    assert "/aws/ecs/default/shurly-api-5fdb" in result.stdout


def test_for_real_needs_the_owners_email_typed_back(aws):
    refused = _run(aws, *ARGS, "--for-real", stdin="yes\n")

    assert refused.returncode == 1
    assert not [
        call
        for call in _calls(aws)
        if call[:2] in (["ecs", "register-task-definition"], ["ecs", "run-task"])
    ]

    confirmed = _run(aws, *ARGS, "--for-real", stdin="owner@griddo.io\n")

    assert confirmed.returncode == 0, confirmed.stderr
    assert "--dry-run" not in _command(aws)


def test_a_file_missing_from_the_bucket_stops_it_before_anything_runs(aws):
    result = _run(aws, *ARGS, FAKE_AWS_MISSING="review.csv")

    assert result.returncode == 1
    assert "review.csv isn't there" in result.stderr
    assert [call[:2] for call in _calls(aws)] == [["s3", "ls"], ["s3", "ls"]]


@pytest.mark.parametrize(
    "args",
    [
        ("--bucket", "b", "--prefix", "p"),  # no --as
        ("--bucket", "b", "--as", "o@griddo.io", "--prefix"),  # --prefix with no value
        ("--bucket", "b", "--prefix", "p", "--as", "o@griddo.io", "--typo"),
    ],
)
def test_a_wrong_call_prints_the_usage(aws, args):
    result = _run(aws, *args)

    assert (result.returncode, "usage:" in result.stderr) == (2, True)
    assert not (aws / "calls.jsonl").exists()
