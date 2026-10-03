"""
`scripts/run_backfill_previews.sh` (ROADMAP 8.7): the backfill of links' page previews and icons,
`python -m server.tools.previews backfill`, as a one-off ECS task, from the live service's image,
environment and network (which reaches the internet, to fetch the pages), like the places
backfill's (scripts/one_off_task.sh, which they share). Run against the same fake `aws`.

- A dry run unless --for-real, which needs the service's name typed back.
- One container, the live one's image and environment, and no task role: it reads nothing from AWS.
- The service's secrets never reach the terminal; the task definition and the local files are
  deleted at the end, whatever happened.
"""

import json
from pathlib import Path

import pytest

from tests import test_run_shlink_import as shared
from tests.test_run_shlink_import import LIVE, NETWORK, NEW_TD, SECRETS, SERVICE_TD, _calls

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_backfill_previews.sh"

pytestmark = pytest.mark.skipif(shared.shutil.which("jq") is None, reason="the script needs jq")

aws = shared.aws  # the fixture: the fake `aws` first on PATH


def _run(state: Path, *args: str, stdin: str = "", **extra):
    return shared._run(state, *args, stdin=stdin, script=SCRIPT, **extra)


def _command(state: Path) -> list[str]:
    run = json.loads((state / "run-task.json").read_text())
    (override,) = run["overrides"]["containerOverrides"]
    assert override["name"] == "backfill"
    return override["command"]


def test_a_dry_run_by_default(aws):
    result = _run(aws)

    assert result.returncode == 0, result.stderr
    assert _command(aws) == ["python", "-m", "server.tools.previews", "backfill"]
    assert "dry run" in result.stdout


def test_the_task_is_the_live_services_container_and_no_role(aws):
    _run(aws)

    registered = json.loads((aws / "registered.json").read_text())
    (backfill,) = registered["containerDefinitions"]
    live = LIVE["containerDefinitions"][0]
    assert registered["family"] == "shurly-backfill-previews"
    assert "taskRoleArn" not in registered
    assert registered["executionRoleArn"] == LIVE["executionRoleArn"]
    assert registered["runtimePlatform"] == LIVE["runtimePlatform"]
    assert (backfill["image"], backfill["environment"]) == (live["image"], live["environment"])
    assert backfill["logConfiguration"]["options"] == {
        **live["logConfiguration"]["options"],
        "awslogs-stream-prefix": "backfill-previews",
    }

    run = json.loads((aws / "run-task.json").read_text())
    assert (run["network"], run["task_definition"]) == (NETWORK, NEW_TD)
    described = [call for call in _calls(aws) if call[:2] == ["ecs", "describe-task-definition"]]
    assert [call[call.index("--task-definition") + 1] for call in described] == [SERVICE_TD]


def test_it_stops_during_a_rollout(aws):
    deployments = [
        {
            "status": "PRIMARY",
            "taskDefinition": SERVICE_TD + "-new",
            "networkConfiguration": NETWORK,
        },
        {"status": "ACTIVE", "taskDefinition": SERVICE_TD, "networkConfiguration": NETWORK},
    ]

    result = _run(aws, FAKE_DEPLOYMENTS=json.dumps(deployments))

    assert result.returncode == 1
    assert "deployment" in result.stderr
    assert not [call for call in _calls(aws) if call[:2] == ["ecs", "run-task"]]


def test_its_output_from_cloudwatch_and_no_secret(aws):
    result = _run(aws)

    assert "[backfill-previews/backfill/abc123]" in result.stdout
    assert not [secret for secret in SECRETS if secret in result.stdout + result.stderr]


def test_for_real_needs_the_services_name_typed_back(aws):
    refused = _run(aws, "--for-real", stdin="yes\n")

    assert refused.returncode == 1
    assert not (aws / "calls.jsonl").exists()  # not one call to AWS

    confirmed = _run(aws, "--for-real", stdin="shurly-api\n")

    assert confirmed.returncode == 0, confirmed.stderr
    assert _command(aws) == ["python", "-m", "server.tools.previews", "backfill", "--for-real"]


def test_a_failed_backfill_fails_the_script_and_still_cleans_up(aws):
    result = _run(aws, FAKE_IMPORT_EXIT="1")

    assert result.returncode == 1
    assert "exited with 1" in result.stderr
    calls = _calls(aws)
    assert ["ecs", "delete-task-definitions", "--task-definitions", NEW_TD] in calls
    assert not Path((aws / "registered-from").read_text()).exists()


def test_a_wrong_call_prints_the_usage(aws):
    result = _run(aws, "--typo")

    assert (result.returncode, "usage:" in result.stderr) == (2, True)
    assert not (aws / "calls.jsonl").exists()
