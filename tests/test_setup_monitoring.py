"""
`scripts/setup_monitoring.sh` (ROADMAP 6.4): applies infra/monitoring/ (metric filters, alarms, the
`shurly` dashboard, the saved Logs Insights queries) and the SNS topic that emails the alarms. Run
here against a fake `aws` that answers as AWS would, keeps what it was given, and records every
call, so what the script would do in AWS is checked without AWS. No real credentials reach it:
the AWS config and credential files point at nothing and HOME is the test's directory.

- A dry run unless --for-real (the region typed back): the same lookups, then the list of what it
  would create or update, and no write call.
- The ALB, the service's two target groups and the RDS instance are looked up and replace the
  definitions' placeholders; a failed lookup stops the script before any write.
- Idempotent: a second run subscribes nobody new and updates the saved queries by id.
- --test-alarm NAME sets that alarm, and only it, to ALARM.
"""

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "setup_monitoring.sh"
DEFS = ROOT / "infra" / "monitoring"

ACCOUNT = "123456789012"
REGION = "eu-south-2"
LOG_GROUP = "/aws/ecs/default/shurly-api-5fdb"
DB = "shurly-db"
EMAIL = "daniel.serrano@griddo.io"
TOPIC_ARN = f"arn:aws:sns:{REGION}:{ACCOUNT}:shurly-alerts"
ELB = f"arn:aws:elasticloadbalancing:{REGION}:{ACCOUNT}"
ALB_ARN = f"{ELB}:loadbalancer/app/ecs-express-gateway-alb-d37ca364/8d6cb22fed5c0e8b"
ALB = "app/ecs-express-gateway-alb-d37ca364/8d6cb22fed5c0e8b"
HTTPS = f"{ELB}:listener/app/ecs-express-gateway-alb-d37ca364/8d6cb22fed5c0e8b/f182b836d7cff456"
HTTP = f"{ELB}:listener/app/ecs-express-gateway-alb-d37ca364/8d6cb22fed5c0e8b/0a1b2c3d4e5f6a7b"
TG_BLUE = f"{ELB}:targetgroup/ecs-gateway-tg-1a2b3c/1111111111111111"
TG_GREEN = f"{ELB}:targetgroup/ecs-gateway-tg-4d5e6f/2222222222222222"
TG_OTHER = f"{ELB}:targetgroup/ecs-gateway-tg-other/3333333333333333"
TGS = (
    "targetgroup/ecs-gateway-tg-1a2b3c/1111111111111111",
    "targetgroup/ecs-gateway-tg-4d5e6f/2222222222222222",
)

ALARMS = [alarm["AlarmName"] for alarm in json.loads((DEFS / "alarms.json").read_text())]
FILTERS = [f["filterName"] for f in json.loads((DEFS / "metric-filters.json").read_text())]
QUERIES = {q["name"]: q["queryString"] for q in json.loads((DEFS / "queries.json").read_text())}

# What `aws` reads: describe, list, get, and sts. Anything else writes.
READ_VERBS = ("describe-", "list-", "get-")


def _forward(*weights):
    return [
        {
            "Type": "forward",
            "Order": 1,
            "ForwardConfig": {
                "TargetGroups": [{"TargetGroupArn": tg, "Weight": w} for tg, w in weights]
            },
        }
    ]


def _host(*hosts):
    return [
        {"Field": "host-header", "Values": list(hosts), "HostHeaderConfig": {"Values": list(hosts)}}
    ]


def _rules(express=None, custom=None):
    """The HTTPS listener's rules as Express and the custom-domain setup leave them."""
    express = express if express is not None else [(TG_BLUE, 100), (TG_GREEN, 0)]
    custom = custom if custom is not None else [(TG_BLUE, 100), (TG_GREEN, 0)]
    return [
        {
            "RuleArn": f"{ELB}:listener-rule/2",
            "Priority": "2",
            "Conditions": _host("other-api.ecs.eu-south-2.on.aws"),
            "Actions": _forward((TG_OTHER, 100)),
            "IsDefault": False,
        },
        {
            "RuleArn": f"{ELB}:listener-rule/4",
            "Priority": "4",
            "Conditions": _host("shurly-api.ecs.eu-south-2.on.aws"),
            "Actions": _forward(*express),
            "IsDefault": False,
        },
        {
            "RuleArn": f"{ELB}:listener-rule/11",
            "Priority": "11",
            "Conditions": _host("links.griddo.io"),
            "Actions": [
                {"Type": "redirect", "Order": 1, "RedirectConfig": {"Host": "shurly.griddo.io"}}
            ],
            "IsDefault": False,
        },
        {
            "RuleArn": f"{ELB}:listener-rule/12",
            "Priority": "12",
            "Conditions": _host("shurly.griddo.io", "go.griddo.io"),
            "Actions": _forward(*custom),
            "IsDefault": False,
        },
        {
            "RuleArn": f"{ELB}:listener-rule/default",
            "Priority": "default",
            "Conditions": [],
            "Actions": [{"Type": "fixed-response", "FixedResponseConfig": {"StatusCode": "404"}}],
            "IsDefault": True,
        },
    ]


def _world(**changes):
    world = {
        "account": ACCOUNT,
        "log_groups": [LOG_GROUP, "/aws/lambda/ecs-alb-rule-sync"],
        "db_instances": [DB],
        "load_balancers": {
            "ecs-express-gateway-alb-d37ca364": ALB_ARN,
            "internal-other": f"{ELB}:loadbalancer/app/internal-other/9999999999999999",
        },
        "listeners": {ALB_ARN: [HTTP, HTTPS]},
        "rules": {
            HTTP: [
                {
                    "RuleArn": f"{ELB}:listener-rule/http-default",
                    "Priority": "default",
                    "Conditions": [],
                    "Actions": [{"Type": "redirect", "RedirectConfig": {"Protocol": "HTTPS"}}],
                    "IsDefault": True,
                }
            ],
            HTTPS: _rules(),
        },
        "topics": {},
        "subscriptions": {},
        "metric_filters": {},
        "alarms": {},
        "dashboards": {},
        "queries": {},
        "next_id": 1,
    }
    world.update(changes)
    return world


FAKE_AWS = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, sys
    from pathlib import Path

    state = Path(os.environ["FAKE_AWS_STATE"])
    world_file = state / "aws.json"
    world = json.loads(world_file.read_text())
    args = sys.argv[1:]
    globals_ = {}
    while args and args[0] in ("--profile", "--region"):
        globals_[args[0]] = args[1]
        args = args[2:]

    def option(name):
        return args[args.index(name) + 1] if name in args else None

    def options(name):
        if name not in args:
            return []
        rest = args[args.index(name) + 1:]
        values = []
        for value in rest:
            if value.startswith("--"):
                break
            values.append(value)
        return values

    # JSON passed as file:// is read now: the script deletes its files when it ends.
    payload = None
    for name in ("--cli-input-json", "--dashboard-body"):
        value = option(name)
        if value is not None:
            if not value.startswith("file://"):
                print("expected file://, got " + value, file=sys.stderr)
                sys.exit(98)
            payload = json.loads(Path(value[len("file://"):]).read_text())
    with open(state / "calls.jsonl", "a") as log:
        log.write(json.dumps({"args": args, "profile": globals_.get("--profile"),
                              "region": globals_.get("--region"), "payload": payload}) + "\\n")

    def out(obj):
        print(json.dumps(obj))

    def save():
        world_file.write_text(json.dumps(world))

    def fail(code, message):
        print(f"An error occurred ({code}) when calling the operation: {message}", file=sys.stderr)
        sys.exit(254)

    region, account = globals_.get("--region"), world["account"]
    command = tuple(args[:2])
    if command == ("sts", "get-caller-identity"):
        out({"UserId": "AROAEXAMPLE:operator", "Account": account,
             "Arn": f"arn:aws:sts::{account}:assumed-role/Admin/operator"})
    elif command == ("logs", "describe-log-groups"):
        prefix = option("--log-group-name-prefix") or ""
        out({"logGroups": [{"logGroupName": g} for g in world["log_groups"] if g.startswith(prefix)]})
    elif command == ("rds", "describe-db-instances"):
        ident = option("--db-instance-identifier")
        if ident not in world["db_instances"]:
            fail("DBInstanceNotFound", f"DBInstance {ident} not found.")
        out({"DBInstances": [{"DBInstanceIdentifier": ident, "DBInstanceStatus": "available"}]})
    elif command == ("elbv2", "describe-load-balancers"):
        out({"LoadBalancers": [{"LoadBalancerName": n, "LoadBalancerArn": a, "Type": "application"}
                               for n, a in world["load_balancers"].items()]})
    elif command == ("elbv2", "describe-listeners"):
        lb = option("--load-balancer-arn")
        out({"Listeners": [{"ListenerArn": arn, "LoadBalancerArn": lb}
                           for arn in world["listeners"].get(lb, [])]})
    elif command == ("elbv2", "describe-rules"):
        out({"Rules": world["rules"].get(option("--listener-arn"), [])})
    elif command == ("sns", "list-topics"):
        out({"Topics": [{"TopicArn": arn} for arn in world["topics"].values()]})
    elif command == ("sns", "create-topic"):
        name = option("--name")
        arn = world["topics"].setdefault(name, f"arn:aws:sns:{region}:{account}:{name}")
        save()
        out({"TopicArn": arn})
    elif command == ("sns", "list-subscriptions-by-topic"):
        arn = option("--topic-arn")
        if arn not in world["topics"].values():
            fail("NotFound", "Topic does not exist")
        out({"Subscriptions": world["subscriptions"].get(arn, [])})
    elif command == ("sns", "subscribe"):
        arn = option("--topic-arn")
        world["subscriptions"].setdefault(arn, []).append({
            "SubscriptionArn": "PendingConfirmation", "Owner": account,
            "Protocol": option("--protocol"), "Endpoint": option("--notification-endpoint"),
            "TopicArn": arn})
        save()
        out({"SubscriptionArn": "pending confirmation"})
    elif command == ("logs", "describe-metric-filters"):
        group = option("--log-group-name")
        out({"metricFilters": [f for f in world["metric_filters"].values()
                               if f["logGroupName"] == group]})
    elif command == ("logs", "put-metric-filter"):
        if payload["logGroupName"] not in world["log_groups"]:
            fail("ResourceNotFoundException", "The specified log group does not exist.")
        world["metric_filters"][payload["filterName"]] = payload
        save()
    elif command == ("cloudwatch", "describe-alarms"):
        names = options("--alarm-names")
        out({"MetricAlarms": [{"AlarmName": n, "StateValue": "OK"}
                              for n in names if n in world["alarms"]],
             "CompositeAlarms": []})
    elif command == ("cloudwatch", "put-metric-alarm"):
        world["alarms"][payload["AlarmName"]] = payload
        save()
    elif command == ("cloudwatch", "list-dashboards"):
        prefix = option("--dashboard-name-prefix") or ""
        out({"DashboardEntries": [{"DashboardName": n} for n in world["dashboards"]
                                  if n.startswith(prefix)]})
    elif command == ("cloudwatch", "put-dashboard"):
        world["dashboards"][option("--dashboard-name")] = payload
        save()
        out({"DashboardValidationMessages": []})
    elif command == ("logs", "describe-query-definitions"):
        prefix = option("--query-definition-name-prefix") or ""
        # As AWS (found by a dry run against the real account): "QueryNamePrefix parameter can not
        # starts or ends with '/' and must not contains consecutive '/'" (InvalidParameterException).
        if prefix.startswith("/") or prefix.endswith("/") or "//" in prefix:
            sys.stderr.write("An error occurred (InvalidParameterException) when calling the "
                             "DescribeQueryDefinitions operation: QueryNamePrefix parameter can not "
                             "starts or ends with '/'")
            sys.exit(254)
        out({"queryDefinitions": [{"queryDefinitionId": i, **q} for i, q in world["queries"].items()
                                  if q["name"].startswith(prefix)]})
    elif command == ("logs", "put-query-definition"):
        qid = payload.get("queryDefinitionId")
        if qid is None:
            qid = f"qd-{world['next_id']}"
            world["next_id"] += 1
        elif qid not in world["queries"]:
            fail("ResourceNotFoundException", "Query definition not found")
        world["queries"][qid] = {k: payload[k] for k in ("name", "queryString", "logGroupNames")}
        save()
        out({"queryDefinitionId": qid})
    elif command == ("cloudwatch", "set-alarm-state"):
        if option("--alarm-name") not in world["alarms"]:
            fail("ResourceNotFound", "alarm does not exist")
    else:
        print("unexpected call: " + " ".join(args), file=sys.stderr)
        sys.exit(99)
    """
)

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="the script needs jq")


class Fake:
    """A fake `aws` first on PATH, its world (aws.json) and the calls it was asked (calls.jsonl)."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path
        self.bin = tmp_path / "bin"
        self.state = tmp_path / "state"
        self.bin.mkdir()
        self.state.mkdir()
        fake = self.bin / "aws"
        fake.write_text(FAKE_AWS)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.world = _world()

    @property
    def world(self) -> dict:
        return json.loads((self.state / "aws.json").read_text())

    @world.setter
    def world(self, value: dict) -> None:
        (self.state / "aws.json").write_text(json.dumps(value))

    def run(self, *args: str, stdin: str = "", **extra: str) -> subprocess.CompletedProcess:
        (self.state / "calls.jsonl").write_text("")
        env = {
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            # No real AWS: no config, no credentials, no profile from the developer's shell.
            "HOME": str(self.home),
            "AWS_CONFIG_FILE": str(self.home / "no-aws-config"),
            "AWS_SHARED_CREDENTIALS_FILE": str(self.home / "no-aws-credentials"),
            "FAKE_AWS_STATE": str(self.state),
            **extra,
        }
        assert shutil.which("aws", path=env["PATH"]) == str(self.bin / "aws")
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=env,
            input=stdin,
            capture_output=True,
            encoding="utf-8",
            timeout=120,
        )

    def for_real(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        return self.run("--for-real", *args, stdin=f"{REGION}\n", **extra)

    def calls(self) -> list[dict]:
        text = (self.state / "calls.jsonl").read_text()
        return [json.loads(line) for line in text.splitlines()]

    def writes(self) -> list[dict]:
        return [c for c in self.calls() if not _is_read(c["args"])]

    def payloads(self, verb: str) -> list:
        return [c["payload"] for c in self.calls() if c["args"][1] == verb]


def _is_read(args: list[str]) -> bool:
    return args[0] == "sts" or args[1].startswith(READ_VERBS)


@pytest.fixture
def aws(tmp_path) -> Fake:
    return Fake(tmp_path)


def _placeholders(value) -> list[str]:
    """Every string in a JSON value that still has a `${`."""
    if isinstance(value, str):
        return [value] if "${" in value else []
    if isinstance(value, dict):
        return [s for v in value.values() for s in _placeholders(v)]
    if isinstance(value, list):
        return [s for v in value for s in _placeholders(v)]
    return []


# --- Dry run ---------------------------------------------------------------------------------------


def test_a_dry_run_looks_everything_up_writes_nothing_and_lists_it_all(aws):
    result = aws.run()

    assert result.returncode == 0, result.stderr
    calls = aws.calls()
    assert calls, "the dry run looked nothing up"
    assert aws.writes() == []
    # Every call goes to the operator's profile and region.
    assert {(c["profile"], c["region"]) for c in calls} == {("griddo-main", REGION)}
    services = {tuple(c["args"][:2]) for c in calls}
    assert {
        ("sts", "get-caller-identity"),
        ("logs", "describe-log-groups"),
        ("rds", "describe-db-instances"),
        ("elbv2", "describe-load-balancers"),
        ("elbv2", "describe-rules"),
    } <= services

    out = result.stdout
    assert "dry run" in out
    assert f"topic shurly-alerts: create ({TOPIC_ARN})" in out
    assert f"subscription {EMAIL}: create" in out
    for name in FILTERS:
        assert f"metric filter {name}: create" in out
    for name in ALARMS:
        assert f"alarm {name}: create" in out
    assert "dashboard shurly: create" in out
    for name in QUERIES:
        assert f"saved query {name}: create" in out
    # What was found, shown before the plan.
    assert ALB in out and TGS[0] in out and TGS[1] in out and DB in out and LOG_GROUP in out


def test_a_dry_run_after_a_real_one_says_update(aws):
    assert aws.for_real().returncode == 0

    result = aws.run()

    assert result.returncode == 0, result.stderr
    assert aws.writes() == []
    out = result.stdout
    assert "topic shurly-alerts: exists" in out
    assert f"subscription {EMAIL}: exists, pending confirmation" in out
    for name in [*FILTERS, *ALARMS]:
        assert f" {name}: update" in out
    assert "dashboard shurly: update" in out
    for name in QUERIES:
        assert f"saved query {name}: update" in out


# --- Real run --------------------------------------------------------------------------------------


def test_a_real_run_applies_every_definition_with_the_discovered_values(aws):
    result = aws.for_real()

    assert result.returncode == 0, result.stderr
    writes = aws.writes()
    verbs = [c["args"][1] for c in writes]
    assert verbs.count("create-topic") == 1
    assert verbs.count("subscribe") == 1
    assert verbs.count("put-metric-filter") == len(FILTERS)
    assert verbs.count("put-metric-alarm") == len(ALARMS)
    assert verbs.count("put-dashboard") == 1
    assert verbs.count("put-query-definition") == len(QUERIES)
    assert len(verbs) == 3 + len(FILTERS) + len(ALARMS) + len(QUERIES)

    # No placeholder left anywhere AWS was given.
    for call in writes:
        assert _placeholders(call["payload"]) == [], call["args"]

    subscribe = next(c["args"] for c in writes if c["args"][1] == "subscribe")
    assert subscribe[subscribe.index("--topic-arn") + 1] == TOPIC_ARN
    assert subscribe[subscribe.index("--protocol") + 1] == "email"
    assert subscribe[subscribe.index("--notification-endpoint") + 1] == EMAIL

    filters = aws.payloads("put-metric-filter")
    assert [f["filterName"] for f in filters] == FILTERS
    assert {f["logGroupName"] for f in filters} == {LOG_GROUP}

    alarms = {a["AlarmName"]: a for a in aws.payloads("put-metric-alarm")}
    assert list(alarms) == ALARMS
    for alarm in alarms.values():
        assert alarm["AlarmActions"] == [TOPIC_ARN]
        assert alarm["OKActions"] == [TOPIC_ARN]
    assert alarms["shurly-alb-5xx"]["Dimensions"] == [{"Name": "LoadBalancer", "Value": ALB}]
    assert alarms["shurly-db-storage-low"]["Dimensions"] == [
        {"Name": "DBInstanceIdentifier", "Value": DB}
    ]
    healthy = [
        m["MetricStat"]["Metric"]["Dimensions"]
        for m in alarms["shurly-no-healthy-target"]["Metrics"]
        if "MetricStat" in m
    ]
    assert healthy == [
        [{"Name": "LoadBalancer", "Value": ALB}, {"Name": "TargetGroup", "Value": TGS[0]}],
        [{"Name": "LoadBalancer", "Value": ALB}, {"Name": "TargetGroup", "Value": TGS[1]}],
    ]

    dashboard_call = next(c for c in writes if c["args"][1] == "put-dashboard")
    args = dashboard_call["args"]
    assert args[args.index("--dashboard-name") + 1] == "shurly"
    body = json.dumps(dashboard_call["payload"])
    assert ALB in body and TGS[0] in body and TGS[1] in body and f'"{DB}"' in body
    assert f"SOURCE '{LOG_GROUP}'" in body

    queries = aws.payloads("put-query-definition")
    assert {q["name"]: q["queryString"] for q in queries} == QUERIES
    for query in queries:
        assert query["logGroupNames"] == [LOG_GROUP]
        assert "queryDefinitionId" not in query

    assert "shurly-alerts" in aws.world["topics"]
    assert "FOR REAL" in result.stdout


def test_a_second_real_run_subscribes_nobody_new_and_updates_the_queries_by_id(aws):
    assert aws.for_real().returncode == 0
    first = aws.world

    result = aws.for_real()

    assert result.returncode == 0, result.stderr
    verbs = [c["args"][1] for c in aws.writes()]
    assert "subscribe" not in verbs
    second = aws.world
    assert second["subscriptions"] == first["subscriptions"]
    assert len(second["subscriptions"][TOPIC_ARN]) == 1
    assert second["topics"] == first["topics"]
    # The saved queries: the same ids, none added.
    assert sorted(second["queries"]) == sorted(first["queries"])
    ids = {q["name"]: i for i, q in first["queries"].items()}
    queries = aws.payloads("put-query-definition")
    assert len(queries) == len(QUERIES)
    for query in queries:
        assert query["queryDefinitionId"] == ids[query["name"]]
    # Upserts, the same set of names.
    assert sorted(second["alarms"]) == sorted(ALARMS)
    assert sorted(second["metric_filters"]) == sorted(FILTERS)


def test_a_confirmed_subscription_with_another_case_is_not_doubled(aws):
    world = aws.world
    world["topics"] = {"shurly-alerts": TOPIC_ARN}
    world["subscriptions"] = {
        TOPIC_ARN: [
            {
                "SubscriptionArn": f"{TOPIC_ARN}:6f1c2d3e",
                "Protocol": "email",
                "Endpoint": EMAIL.upper(),
                "TopicArn": TOPIC_ARN,
            }
        ]
    }
    aws.world = world

    result = aws.for_real()

    assert result.returncode == 0, result.stderr
    assert "subscribe" not in [c["args"][1] for c in aws.writes()]
    assert f"subscription {EMAIL}: exists, confirmed" in result.stdout


def test_alert_email_can_be_set(aws):
    result = aws.for_real(ALERT_EMAIL="ops@griddo.io")

    assert result.returncode == 0, result.stderr
    subscribe = next(c["args"] for c in aws.writes() if c["args"][1] == "subscribe")
    assert subscribe[subscribe.index("--notification-endpoint") + 1] == "ops@griddo.io"


# --- Failed lookups --------------------------------------------------------------------------------


def _no_log_group(world):
    world["log_groups"] = ["/aws/ecs/default/shurly-api-5fdb-old"]


def _no_db(world):
    world["db_instances"] = []


def _one_target_group(world):
    world["rules"][next(iter(world["listeners"].values()))[1]] = _rules(
        express=[(TG_BLUE, 100)], custom=[(TG_BLUE, 100)]
    )


def _three_target_groups(world):
    world["rules"][next(iter(world["listeners"].values()))[1]] = _rules(
        custom=[(TG_BLUE, 100), (TG_OTHER, 0)]
    )


def _no_alb(world):
    world["load_balancers"] = {"internal-other": f"{ELB}:loadbalancer/app/internal-other/9"}


@pytest.mark.parametrize(
    ("breaks", "message"),
    [
        (_no_log_group, "No log group"),
        (_no_db, "No RDS instance shurly-db"),
        (_one_target_group, "found 1"),
        (_three_target_groups, "found 3"),
        (_no_alb, "Expected one load balancer"),
    ],
)
def test_a_failed_lookup_stops_before_any_write(aws, breaks, message):
    world = aws.world
    breaks(world)
    aws.world = world

    result = aws.for_real()

    assert result.returncode != 0
    assert message in result.stderr
    assert aws.writes() == []


def test_the_target_groups_are_found_from_either_rule(aws):
    """Express's rule alone, or the custom domain's alone, still names the two."""
    world = aws.world
    https = world["listeners"][ALB_ARN][1]
    world["rules"][https] = [r for r in _rules() if r["Priority"] != "12"]
    aws.world = world

    result = aws.run()

    assert result.returncode == 0, result.stderr
    assert f"{TGS[0]}, {TGS[1]}" in result.stdout


# --- Testing an alarm ------------------------------------------------------------------------------


def test_test_alarm_refuses_an_unknown_name(aws):
    assert aws.for_real().returncode == 0

    result = aws.run("--test-alarm", "shurly-nonsense", "--for-real", stdin=f"{REGION}\n")

    assert result.returncode != 0
    assert "No alarm shurly-nonsense" in result.stderr
    assert aws.calls() == []


def test_test_alarm_sets_that_alarm_only(aws):
    assert aws.for_real().returncode == 0

    result = aws.run("--test-alarm", "shurly-api-5xx", "--for-real", stdin=f"{REGION}\n")

    assert result.returncode == 0, result.stderr
    writes = aws.writes()
    assert [c["args"] for c in writes] == [
        [
            "cloudwatch",
            "set-alarm-state",
            "--alarm-name",
            "shurly-api-5xx",
            "--state-value",
            "ALARM",
            "--state-reason",
            "Test from setup_monitoring.sh",
        ]
    ]


def test_test_alarm_is_a_dry_run_without_for_real(aws):
    assert aws.for_real().returncode == 0

    result = aws.run("--test-alarm", "shurly-api-5xx")

    assert result.returncode == 0, result.stderr
    assert aws.writes() == []
    assert "Would set shurly-api-5xx to ALARM" in result.stdout


def test_test_alarm_needs_the_alarm_to_exist_in_aws(aws):
    result = aws.run("--test-alarm", "shurly-api-5xx", "--for-real", stdin=f"{REGION}\n")

    assert result.returncode != 0
    assert "doesn't exist in AWS yet" in result.stderr
    assert aws.writes() == []


# --- Confirmation and usage ------------------------------------------------------------------------


@pytest.mark.parametrize("typed", ["eu-west-1\n", "\n", ""])
def test_for_real_with_a_wrong_region_does_nothing(aws, typed):
    result = aws.run("--for-real", stdin=typed)

    assert result.returncode != 0
    assert "Not confirmed" in result.stderr
    assert aws.calls() == []


@pytest.mark.parametrize(
    "args",
    [
        ("--bogus",),
        ("extra",),
        ("--test-alarm",),
        ("--test-alarm", "--for-real"),
        ("--test-alarm", "a", "--test-alarm", "b"),
        ("--help",),
    ],
)
def test_usage_errors_exit_2(aws, args):
    result = aws.run(*args)

    assert result.returncode == 2
    assert "usage:" in result.stderr
    assert aws.calls() == []
