"""
The ecs-alb-rule-sync Lambda (infra/ecs-alb-rule-sync/alb-rule-sync.py).

It keeps the custom-domain ALB rules (priority 10+) in step with the rules
ECS Express manages (priority 1-5). It used to sync only on
SERVICE_DEPLOYMENT_COMPLETED, which ECS emits ~1 min after stopping the old
task — so s.griddo.io pointed at an empty target group and returned 503 in
between, and never followed the canary. These tests pin the fix: on
IN_PROGRESS it follows the deployment until ECS reports it finished.

The Lambda imports boto3 at module level; boto3 isn't a project dependency,
so it's stubbed before import and the module's clients are replaced by fakes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

LAMBDA_PATH = Path(__file__).resolve().parents[1] / "infra" / "ecs-alb-rule-sync" / "alb-rule-sync.py"
SERVICE_ARN = "arn:aws:ecs:eu-south-2:686255983646:service/default/shurly-api"
OLD_TG = "arn:tg/old"
NEW_TG = "arn:tg/new"


def _load_lambda():
    sys.modules.setdefault("boto3", types.SimpleNamespace(client=lambda *a, **k: object()))
    spec = importlib.util.spec_from_file_location("alb_rule_sync", LAMBDA_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rule(priority, weights):
    return {
        "Priority": priority,
        "RuleArn": f"arn:rule/{priority}",
        "Actions": [{
            "Type": "forward",
            "ForwardConfig": {
                "TargetGroups": [{"TargetGroupArn": tg, "Weight": w} for tg, w in weights.items()]
            },
        }],
    }


class FakeElb:
    """Express's rule 4 walks through `express_steps`, one per describe_rules."""

    def __init__(self, express_steps, custom_weights, extra_rules=()):
        self.express_steps = list(express_steps)
        self.custom = dict(custom_weights)
        self.extra_rules = list(extra_rules)
        self.modified = []

    def describe_rules(self, ListenerArn):
        weights = self.express_steps.pop(0) if len(self.express_steps) > 1 else self.express_steps[0]
        return {"Rules": [_rule("4", weights), _rule("12", self.custom), *self.extra_rules]}

    def modify_rule(self, RuleArn, Actions):
        tgs = Actions[0]["ForwardConfig"]["TargetGroups"]
        self.modified.append((RuleArn, {t["TargetGroupArn"]: t["Weight"] for t in tgs}))
        if RuleArn == "arn:rule/12":
            self.custom = {t["TargetGroupArn"]: t["Weight"] for t in tgs}


class FakeEcs:
    """Reports the deployment IN_PROGRESS for `in_progress_polls` calls, then COMPLETED."""

    def __init__(self, in_progress_polls, deployment_id="ecs-svc/1"):
        self.remaining = in_progress_polls
        self.deployment_id = deployment_id
        self.calls = 0

    def describe_services(self, cluster, services):
        assert cluster == "default"
        self.calls += 1
        state = "IN_PROGRESS" if self.remaining > 0 else "COMPLETED"
        self.remaining -= 1
        return {"services": [{"deployments": [{"id": self.deployment_id, "rolloutState": state}]}]}


class FakeLambda:
    def __init__(self):
        self.invocations = []

    def invoke(self, FunctionName, InvocationType, Payload):
        self.invocations.append((FunctionName, InvocationType, json.loads(Payload)))


class FakeContext:
    invoked_function_arn = "arn:aws:lambda:eu-south-2:686255983646:function:ecs-alb-rule-sync"

    def __init__(self, budget_ms=900_000, per_call_ms=0):
        self.budget = budget_ms
        self.per_call = per_call_ms

    def get_remaining_time_in_millis(self):
        self.budget -= self.per_call
        return self.budget


def _event(name, deployment_id="ecs-svc/1"):
    return {
        "source": "aws.ecs",
        "detail-type": "ECS Deployment State Change",
        "resources": [SERVICE_ARN],
        "detail": {"eventName": name, "deploymentId": deployment_id},
    }


@pytest.fixture
def lam(monkeypatch):
    module = _load_lambda()
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    module.lambda_ = FakeLambda()
    return module


def test_manual_invocation_does_a_single_pass(lam):
    """`aws lambda invoke --payload '{}'` keeps working exactly as before."""
    lam.elbv2 = FakeElb([{OLD_TG: 0, NEW_TG: 100}], {OLD_TG: 100, NEW_TG: 0})
    lam.ecs = FakeEcs(in_progress_polls=99)

    result = lam.lambda_handler({}, FakeContext())

    assert lam.elbv2.modified == [("arn:rule/12", {OLD_TG: 0, NEW_TG: 100})]
    assert lam.ecs.calls == 0, "a manual run must not follow any deployment"
    assert result == ["Synced priority 12 with 4 (weights 0/100 = 0%/100%)"]


def test_no_change_when_already_in_sync(lam):
    lam.elbv2 = FakeElb([{NEW_TG: 100}], {NEW_TG: 100})
    lam.ecs = FakeEcs(in_progress_polls=0)

    assert lam.lambda_handler({}, FakeContext()) == ["No changes needed"]
    assert lam.elbv2.modified == []


def test_in_progress_follows_the_canary_until_completed(lam):
    """The fix: the custom rule tracks every weight change during the rollout."""
    canary = [
        {OLD_TG: 100, NEW_TG: 0},  # rollout starts
        {OLD_TG: 95, NEW_TG: 5},   # canary
        {OLD_TG: 95, NEW_TG: 5},
        {OLD_TG: 0, NEW_TG: 100},  # full shift, before the old task is stopped
        {OLD_TG: 0, NEW_TG: 100},
    ]
    lam.elbv2 = FakeElb(canary, {OLD_TG: 100, NEW_TG: 0})
    lam.ecs = FakeEcs(in_progress_polls=3)

    lam.lambda_handler(_event("SERVICE_DEPLOYMENT_IN_PROGRESS"), FakeContext())

    assert [w for _, w in lam.elbv2.modified] == [
        {OLD_TG: 95, NEW_TG: 5},
        {OLD_TG: 0, NEW_TG: 100},
    ]
    assert lam.elbv2.custom == {OLD_TG: 0, NEW_TG: 100}
    assert lam.ecs.calls == 4, "stops polling once ECS reports the deployment finished"


def test_completed_and_failed_do_a_single_final_pass(lam):
    for name in ("SERVICE_DEPLOYMENT_COMPLETED", "SERVICE_DEPLOYMENT_FAILED"):
        lam.elbv2 = FakeElb([{NEW_TG: 100}], {OLD_TG: 100})
        lam.ecs = FakeEcs(in_progress_polls=99)

        lam.lambda_handler(_event(name), FakeContext())

        assert len(lam.elbv2.modified) == 1, name
        assert lam.ecs.calls == 0, name


def test_stops_when_the_deployment_disappears(lam):
    """A newer deployment can replace the one being followed."""
    lam.elbv2 = FakeElb([{NEW_TG: 100}], {NEW_TG: 100})
    lam.ecs = FakeEcs(in_progress_polls=99, deployment_id="ecs-svc/other")

    lam.lambda_handler(_event("SERVICE_DEPLOYMENT_IN_PROGRESS", "ecs-svc/1"), FakeContext())

    assert lam.ecs.calls == 1


def test_hands_off_to_a_fresh_invocation_before_timing_out(lam):
    """900 s is Lambda's hard ceiling. A rollout that outlives it must not lose
    its follower: the Lambda re-invokes itself asynchronously and carries on.
    (The 27 Sep 2026 release used 613 s of it.)"""
    lam.elbv2 = FakeElb([{NEW_TG: 100}], {NEW_TG: 100})
    lam.ecs = FakeEcs(in_progress_polls=10_000)
    ctx = FakeContext(budget_ms=60_000, per_call_ms=5_000)
    event = _event("SERVICE_DEPLOYMENT_IN_PROGRESS")

    lam.lambda_handler(event, ctx)

    assert ctx.budget > 0, "must return before the timeout"
    assert len(lam.lambda_.invocations) == 1
    fn, kind, payload = lam.lambda_.invocations[0]
    assert fn == FakeContext.invoked_function_arn
    assert kind == "Event", "asynchronous, so this invocation can finish"
    assert payload["detail"] == event["detail"]
    assert payload["resources"] == event["resources"]
    assert payload[lam.HOP_KEY] == 1


def test_hand_offs_are_capped(lam):
    """The chain can't run forever: it stops after MAX_HOPS re-invocations."""
    lam.elbv2 = FakeElb([{NEW_TG: 100}], {NEW_TG: 100})
    lam.ecs = FakeEcs(in_progress_polls=10_000)
    event = {**_event("SERVICE_DEPLOYMENT_IN_PROGRESS"), lam.HOP_KEY: lam.MAX_HOPS}

    lam.lambda_handler(event, FakeContext(budget_ms=60_000, per_call_ms=5_000))

    assert lam.lambda_.invocations == []


def test_no_hand_off_once_the_deployment_ends(lam):
    lam.elbv2 = FakeElb([{NEW_TG: 100}], {NEW_TG: 100})
    lam.ecs = FakeEcs(in_progress_polls=2)

    lam.lambda_handler(_event("SERVICE_DEPLOYMENT_IN_PROGRESS"), FakeContext())

    assert lam.lambda_.invocations == []


def test_manual_and_final_passes_never_hand_off(lam):
    for event in ({}, _event("SERVICE_DEPLOYMENT_COMPLETED")):
        lam.elbv2 = FakeElb([{NEW_TG: 100}], {NEW_TG: 100})
        lam.ecs = FakeEcs(in_progress_polls=10_000)
        lam.lambda_handler(event, FakeContext(budget_ms=1_000))
    assert lam.lambda_.invocations == []


def test_log_reports_real_percentages(lam):
    """ALB weights are relative (Express uses 950/50 during the canary); the
    log used to print them as "950%, 50%"."""
    lam.elbv2 = FakeElb([{OLD_TG: 950, NEW_TG: 50}], {OLD_TG: 1000, NEW_TG: 0})
    lam.ecs = FakeEcs(in_progress_polls=0)

    assert lam.lambda_handler({}, FakeContext()) == [
        "Synced priority 12 with 4 (weights 950/50 = 95%/5%)"
    ]


def test_other_services_mappings_are_still_synced(lam):
    """The Lambda is shared: go.griddo.io (1→10) and links.griddo.io (3→11) too."""
    extra = [
        _rule("1", {"arn:tg/api-new": 100}), _rule("10", {"arn:tg/api-old": 100}),
        _rule("3", {"arn:tg/web": 100}), _rule("11", {"arn:tg/web": 100}),
    ]
    lam.elbv2 = FakeElb([{NEW_TG: 100}], {NEW_TG: 100}, extra_rules=extra)
    lam.ecs = FakeEcs(in_progress_polls=0)

    lam.lambda_handler({}, FakeContext())

    assert lam.elbv2.modified == [("arn:rule/10", {"arn:tg/api-new": 100})]
