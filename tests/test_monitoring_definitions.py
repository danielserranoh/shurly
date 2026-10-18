"""
Phase 6.4 — the monitoring definitions in `infra/monitoring/` (plan_alerting-and-monitoring, T1).

`scripts/setup_monitoring.sh` applies these files as they are, after replacing the placeholders, so what
they say is what production gets: the filter patterns, the alarms' thresholds and actions, the dashboard's
metrics and the saved queries' names.

CloudWatch's filter-pattern syntax can't be run locally, so `_matches` evaluates the subset these filters use
(`$.field = "x"`, `$.field >= N` and the other comparisons, joined by `&&`). It refuses anything else, and it's
tested below, so a pattern outside the subset fails here instead of being half-understood.
"""

import json
import re
from pathlib import Path

import pytest

MONITORING = Path(__file__).resolve().parent.parent / "infra" / "monitoring"
FILES = ["metric-filters.json", "alarms.json", "dashboard.json", "queries.json"]
PLACEHOLDERS = {"ALB", "TG_1", "TG_2", "DB", "LOG_GROUP", "TOPIC_ARN"}
REGION = "eu-south-2"


def _load(name: str):
    return json.loads((MONITORING / name).read_text(encoding="utf-8"))


# --- A local evaluator for the filter patterns ---------------------------------------------------------

_TERM = re.compile(
    r"^\$\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<op>!=|>=|<=|=|>|<)\s*"
    r'(?P<value>"[^"*]*"|-?\d+(?:\.\d+)?)$'
)


def _matches(pattern: str, line: str) -> bool:
    """Whether CloudWatch would count `line` for a JSON filter `pattern` (the subset used here)."""
    body = pattern.strip()
    if not (body.startswith("{") and body.endswith("}")):
        raise ValueError(f"not a JSON filter pattern: {pattern!r}")
    body = body[1:-1]
    if "||" in body or "(" in body or ")" in body:
        raise ValueError(f"outside the supported subset: {pattern!r}")
    try:
        record = json.loads(line)
    except ValueError:
        return False  # CloudWatch never matches a JSON pattern against a line that isn't JSON
    if not isinstance(record, dict):
        return False
    return all(_term_holds(term.strip(), record) for term in body.split("&&"))


def _term_holds(term: str, record: dict) -> bool:
    match = _TERM.match(term)
    if match is None:
        raise ValueError(f"outside the supported subset: {term!r}")
    field, op, raw = match["field"], match["op"], match["value"]
    if field not in record:
        return False
    actual = record[field]
    if raw.startswith('"'):
        if op not in ("=", "!="):
            raise ValueError(f"a string only compares with = or !=: {term!r}")
        equal = isinstance(actual, str) and actual == raw[1:-1]
        return equal if op == "=" else not equal
    # A numeric comparison only holds for a number in the log line.
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return False
    expected = float(raw)
    return {
        "=": actual == expected,
        "!=": actual != expected,
        ">=": actual >= expected,
        "<=": actual <= expected,
        ">": actual > expected,
        "<": actual < expected,
    }[op]


def _line(**fields) -> str:
    return json.dumps({"ts": "2026-10-17T20:00:00.000+00:00", **fields})


def _request(**overrides) -> str:
    """An `http.request` line, as `main.py` writes it."""
    fields = {
        "event": "http.request",
        "request_id": "3f2c9a1e",
        "method": "GET",
        "host": "go.griddo.io",
        "path": "/x",
        "client_ip_source": "cloudfront",
        "status": 502,
        "duration_ms": 3.1,
    }
    return _line(**{**fields, **overrides})


class TestEvaluator:
    """The evaluator has to be right for the pattern tests below to mean anything."""

    def test_string_equality(self):
        assert _matches('{ $.event = "client.error" }', _line(event="client.error"))
        assert not _matches('{ $.event = "client.error" }', _line(event="client.errors"))

    def test_string_inequality(self):
        assert _matches('{ $.event != "a" }', _line(event="b"))
        assert not _matches('{ $.event != "a" }', _line(event="a"))

    def test_numeric_comparisons(self):
        assert _matches("{ $.status >= 500 }", _line(status=500))
        assert _matches("{ $.status >= 500 }", _line(status=503))
        assert not _matches("{ $.status >= 500 }", _line(status=499))
        assert _matches("{ $.status > 499 }", _line(status=500))
        assert not _matches("{ $.status < 400 }", _line(status=400))
        assert _matches("{ $.status <= 400 }", _line(status=400))
        assert _matches("{ $.status = 201 }", _line(status=201))
        assert _matches("{ $.duration_ms >= 2.5 }", _line(duration_ms=3.1))

    def test_and_needs_every_term(self):
        pattern = '{ $.event = "http.request" && $.status >= 500 }'
        assert _matches(pattern, _request(status=500))
        assert not _matches(pattern, _request(status=200))
        assert not _matches(pattern, _line(event="client.error", status=500))

    def test_a_missing_field_never_matches(self):
        assert not _matches('{ $.outcome = "error" }', _line(event="mcp.tool_call"))
        assert not _matches("{ $.status >= 500 }", _line(event="http.request"))

    def test_a_number_compares_with_numbers_only(self):
        assert not _matches("{ $.status >= 500 }", _line(status="502"))
        assert not _matches("{ $.status >= 500 }", _line(status=None))
        assert not _matches('{ $.status = "502" }', _line(status=502))

    def test_a_line_that_isnt_a_json_object_never_matches(self):
        assert not _matches('{ $.event = "client.error" }', "client.error happened")
        assert not _matches('{ $.event = "client.error" }', '["client.error"]')

    @pytest.mark.parametrize(
        "pattern",
        [
            '$.event = "x"',  # no braces
            '{ $.event = "x" || $.event = "y" }',
            '{ ($.event = "x") }',
            "{ $.event IS NULL }",
            '{ $.event = "client.*" }',  # wildcards aren't evaluated
            '{ $.event >= "x" }',
            '{ $.a.b = "x" }',  # nested fields aren't evaluated
            '{ event = "x" }',
        ],
    )
    def test_refuses_what_it_doesnt_evaluate(self, pattern):
        with pytest.raises(ValueError):
            _matches(pattern, _line(event="x"))


# --- The files ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", FILES)
def test_every_file_parses(name):
    assert _load(name)


@pytest.mark.parametrize("name", FILES)
def test_only_the_known_placeholders(name):
    text = (MONITORING / name).read_text(encoding="utf-8")
    used = set(re.findall(r"\$\{([^}]*)\}", text))
    assert used <= PLACEHOLDERS, used - PLACEHOLDERS
    if name != "queries.json":  # a saved query's regex may end in `$`
        # A `$` that isn't a placeholder or a filter pattern's `$.field` would be a typo'd placeholder.
        assert not re.search(r"\$(?![{.])", text)


def test_the_readme_names_every_file_and_placeholder():
    readme = (MONITORING / "README.md").read_text(encoding="utf-8")
    for name in FILES:
        assert name in readme
    for placeholder in PLACEHOLDERS:
        assert "${" + placeholder + "}" in readme
    assert "scripts/setup_monitoring.sh" in readme


# --- Metric filters -----------------------------------------------------------------------------------

FILTER_SAMPLES = {
    "shurly-5xx": (
        _request(status=502),
        _request(status=404),
    ),
    "shurly-rate-limit-store": (
        _line(event="rate_limit.store_failed", limit="login", error="OperationalError"),
        _line(event="rate_limit.exceeded", limit="login"),
    ),
    "shurly-client-errors": (
        _line(
            event="client.error",
            kind="error",
            message="TypeError: x is undefined",
            source="/_astro/app.js:1:200",
            page="/dashboard/",
        ),
        _request(path="/api/v1/client-errors", status=204),
    ),
    "shurly-mcp-tool-errors": (
        _line(
            event="mcp.tool_call",
            request_id="3f2c9a1e",
            tool="create_short_url",
            args=["original_url"],
            user_id="7",
            outcome="error",
            error_type="ToolError",
            http_status=422,
            duration_ms=12.4,
        ),
        _line(
            event="mcp.tool_call",
            request_id="3f2c9a1e",
            tool="create_short_url",
            args=["original_url"],
            user_id="7",
            outcome="ok",
            error_type=None,
            http_status=None,
            duration_ms=12.4,
        ),
    ),
}


def _filters() -> dict:
    return {f["filterName"]: f for f in _load("metric-filters.json")}


def test_the_four_filters():
    assert set(_filters()) == set(FILTER_SAMPLES)


@pytest.mark.parametrize("name", sorted(FILTER_SAMPLES))
def test_filter_matches_its_lines_only(name):
    pattern = _filters()[name]["filterPattern"]
    matching, other = FILTER_SAMPLES[name]
    assert _matches(pattern, matching)
    assert not _matches(pattern, other)


def test_the_5xx_filter_counts_every_5xx_and_nothing_else():
    pattern = _filters()["shurly-5xx"]["filterPattern"]
    for status in (500, 502, 503, 504):
        assert _matches(pattern, _request(status=status))
    for status in (200, 302, 404, 410, 429, 499):
        assert not _matches(pattern, _request(status=status))
    # An MCP line carries `http_status`, not `status`: it's counted by its own `http.request` line.
    assert not _matches(pattern, _line(event="mcp.tool_call", outcome="error", http_status=500))


@pytest.mark.parametrize("name", sorted(FILTER_SAMPLES))
def test_filter_publishes_one_per_line_in_namespace_shurly(name):
    definition = _filters()[name]
    assert definition["logGroupName"] == "${LOG_GROUP}"
    [transformation] = definition["metricTransformations"]
    assert transformation["metricNamespace"] == "Shurly"
    assert transformation["metricValue"] == "1"
    assert transformation["defaultValue"] == 0


def _shurly_metrics() -> set[str]:
    return {
        t["metricName"]
        for f in _load("metric-filters.json")
        for t in f["metricTransformations"]
        if t["metricNamespace"] == "Shurly"
    }


# --- Alarms -------------------------------------------------------------------------------------------

# (threshold, period in seconds, evaluation periods, comparison), as the plan sets them.
ALARMS = {
    "shurly-api-5xx": (5, 300, 1, "GreaterThanOrEqualToThreshold"),
    "shurly-rate-limit-store": (1, 300, 1, "GreaterThanOrEqualToThreshold"),
    "shurly-client-errors": (10, 900, 1, "GreaterThanOrEqualToThreshold"),
    "shurly-alb-5xx": (5, 300, 1, "GreaterThanOrEqualToThreshold"),
    "shurly-no-healthy-target": (1, 60, 3, "LessThanThreshold"),
    "shurly-db-storage-low": (2 * 1024**3, 300, 1, "LessThanThreshold"),
}


def _alarms() -> dict:
    return {a["AlarmName"]: a for a in _load("alarms.json")}


def _period(alarm: dict) -> int:
    if "Metrics" not in alarm:
        return alarm["Period"]
    periods = {m["MetricStat"]["Period"] for m in alarm["Metrics"] if "MetricStat" in m}
    assert len(periods) == 1, periods
    return periods.pop()


def test_the_six_alarms():
    assert set(_alarms()) == set(ALARMS)


@pytest.mark.parametrize("name", sorted(ALARMS))
def test_alarm_condition(name):
    alarm = _alarms()[name]
    threshold, period, evaluations, comparison = ALARMS[name]
    assert alarm["Threshold"] == threshold
    assert _period(alarm) == period
    assert alarm["EvaluationPeriods"] == evaluations
    assert alarm.get("DatapointsToAlarm", evaluations) == evaluations
    assert alarm["ComparisonOperator"] == comparison
    assert alarm["TreatMissingData"] == "notBreaching"


@pytest.mark.parametrize("name", sorted(ALARMS))
def test_alarm_emails_on_alarm_and_on_recovery(name):
    alarm = _alarms()[name]
    assert alarm["AlarmActions"] == ["${TOPIC_ARN}"]
    assert alarm["OKActions"] == ["${TOPIC_ARN}"]
    assert alarm.get("ActionsEnabled", True) is True


@pytest.mark.parametrize("name", sorted(ALARMS))
def test_alarm_description_points_to_the_runbook(name):
    description = _alarms()[name]["AlarmDescription"]
    assert description.endswith("Runbook: DEPLOYMENT.md § Error alerting")
    assert len(description) <= 1024  # CloudWatch's limit


def test_log_alarms_watch_the_filters_metrics():
    alarms = _alarms()
    expected = {
        "shurly-api-5xx": "ApiErrors5xx",
        "shurly-rate-limit-store": "RateLimitStoreFailures",
        "shurly-client-errors": "ClientErrors",
    }
    for name, metric in expected.items():
        assert alarms[name]["Namespace"] == "Shurly"
        assert alarms[name]["MetricName"] == metric
        assert alarms[name]["Statistic"] == "Sum"
        assert metric in _shurly_metrics()


def test_aws_alarms_watch_the_discovered_resources():
    alarms = _alarms()
    alb = alarms["shurly-alb-5xx"]
    assert (alb["Namespace"], alb["MetricName"]) == ("AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count")
    assert alb["Dimensions"] == [{"Name": "LoadBalancer", "Value": "${ALB}"}]

    db = alarms["shurly-db-storage-low"]
    assert (db["Namespace"], db["MetricName"]) == ("AWS/RDS", "FreeStorageSpace")
    assert db["Dimensions"] == [{"Name": "DBInstanceIdentifier", "Value": "${DB}"}]


def test_no_healthy_target_sums_both_target_groups():
    alarm = _alarms()["shurly-no-healthy-target"]
    # A metric-math alarm names no metric of its own.
    assert not {"MetricName", "Namespace", "Statistic", "Period", "Dimensions"} & set(alarm)
    stats = {m["Id"]: m for m in alarm["Metrics"] if "MetricStat" in m}
    target_groups = set()
    for metric in stats.values():
        inner = metric["MetricStat"]["Metric"]
        assert (inner["Namespace"], inner["MetricName"]) == (
            "AWS/ApplicationELB",
            "HealthyHostCount",
        )
        dimensions = {d["Name"]: d["Value"] for d in inner["Dimensions"]}
        assert dimensions["LoadBalancer"] == "${ALB}"
        target_groups.add(dimensions["TargetGroup"])
        assert metric["ReturnData"] is False
    assert target_groups == {"${TG_1}", "${TG_2}"}

    [result] = [m for m in alarm["Metrics"] if m.get("ReturnData")]
    assert result["Expression"].replace(" ", "") == "SUM([" + ",".join(sorted(stats)) + "])"


# --- Dashboard ----------------------------------------------------------------------------------------


def _dashboard_metrics():
    """Every (namespace, metric name) the dashboard's metric widgets draw."""
    for widget in _load("dashboard.json")["widgets"]:
        if widget["type"] != "metric":
            continue
        for row in widget["properties"]["metrics"]:
            names = [part for part in row if isinstance(part, str)]
            assert names[0] != "...", "write every row in full"
            yield names[0], names[1]


def test_dashboard_widgets_are_in_the_region():
    widgets = _load("dashboard.json")["widgets"]
    assert widgets
    for widget in widgets:
        assert widget["type"] in ("metric", "log", "text")
        if widget["type"] != "text":
            assert widget["properties"]["region"] == REGION
        assert widget["x"] + widget["width"] <= 24


def test_dashboard_metrics_exist():
    drawn = set(_dashboard_metrics())
    for namespace, name in drawn:
        if namespace == "Shurly":
            assert name in _shurly_metrics(), name
        else:
            assert namespace in ("AWS/ECS", "AWS/ApplicationELB", "AWS/RDS"), namespace


def test_dashboard_draws_what_the_plan_lists():
    drawn = set(_dashboard_metrics())
    assert {("Shurly", name) for name in _shurly_metrics()} <= drawn
    assert {
        ("AWS/ECS", "CPUUtilization"),
        ("AWS/ECS", "MemoryUtilization"),
        ("AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count"),
        ("AWS/ApplicationELB", "HTTPCode_Target_5XX_Count"),
        ("AWS/ApplicationELB", "HealthyHostCount"),
        ("AWS/ApplicationELB", "TargetResponseTime"),
        ("AWS/RDS", "DatabaseConnections"),
        ("AWS/RDS", "CPUUtilization"),
        ("AWS/RDS", "FreeStorageSpace"),
    } <= drawn


def test_dashboard_ecs_widgets_name_the_service():
    for widget in _load("dashboard.json")["widgets"]:
        if widget["type"] != "metric":
            continue
        for row in widget["properties"]["metrics"]:
            if row[0] == "AWS/ECS":
                dims = row[2:-1] if isinstance(row[-1], dict) else row[2:]
                assert dict(zip(dims[::2], dims[1::2], strict=True)) == {
                    "ClusterName": "default",
                    "ServiceName": "shurly-api",
                }


def test_dashboard_log_widgets_read_the_log_group():
    queries = [
        w["properties"]["query"] for w in _load("dashboard.json")["widgets"] if w["type"] == "log"
    ]
    assert len(queries) == 3
    for query in queries:
        assert query.startswith("SOURCE '${LOG_GROUP}' | ")
    joined = "\n".join(queries)
    assert 'host = "go.griddo.io"' in joined
    # The MCP side is the tool's own time: a `POST /mcp/` line is written when the event stream opens, before
    # the tool runs, so its duration_ms reads ~1 ms whatever the tool does.
    assert 'event = "mcp.tool_call"' in joined
    assert r"/^\/mcp\//" not in joined
    assert r"path like /^\/api\/v1\//" in joined
    assert 'path != "/api/v1/health"' in joined
    assert "status >= 500" in joined


# --- Saved queries ------------------------------------------------------------------------------------


def test_query_names_are_unique_and_under_shurly():
    queries = _load("queries.json")
    names = [q["name"] for q in queries]
    assert len(names) == len(set(names))
    for query in queries:
        assert set(query) == {"name", "queryString"}
        assert query["name"].startswith("shurly/")
        assert query["queryString"].strip()


def test_the_queries_the_plan_lists():
    # 5 from the MCP's README (4 per tool or user, plus one request's trail), 3 web app, client errors, 5xx by path, IP source per host, geo database events, logins.
    queries = _load("queries.json")
    assert len(queries) == 13
    assert sum(q["name"].startswith("shurly/mcp/") for q in queries) == 4
    events = "\n".join(q["queryString"] for q in queries)
    for needle in (
        'event = "mcp.tool_call"',
        'request_id = "<id>"',
        'event = "client.error"',
        "status >= 500",
        "client_ip_source",
        r"event like /^geo\.database/",
        'event = "auth.login"',
    ):
        assert needle in events, needle
