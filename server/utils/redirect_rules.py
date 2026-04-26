"""Phase 3.10.2 — RedirectRule condition evaluator.

A rule's `conditions` field is a list of dicts; the rule matches when ALL
entries match (logical AND). Each entry has shape::

    {"type": "<kind>", "op": "<comparator>", "value": "<expected>"}

Supported `type` values:
- ``device``         -> ios | android | desktop | linux | windows | macos
- ``language``       -> primary subtag of Accept-Language (e.g. "en", "es")
- ``query_param``    -> presence/value match on a query string param
- ``before_date``    -> request time strictly before ISO-8601 timestamp
- ``after_date``     -> request time at or after ISO-8601 timestamp
- ``browser``        -> chrome | safari | firefox | edge | opera | ...

All matchers are case-insensitive on string inputs. Unknown types are treated
as non-matching (fail closed) so a typo never accidentally redirects users.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from server.utils.user_agent import parse_user_agent


def _norm(s: Any) -> str:
    return str(s).strip().lower() if s is not None else ""


def _device_from_ua(parsed: Mapping[str, Any]) -> str:
    """Map parser output to the Shlink-style device family token."""
    os_ = _norm(parsed.get("os"))
    device_type = _norm(parsed.get("device_type"))
    if "ios" in os_:
        return "ios"
    if "android" in os_:
        return "android"
    if "windows" in os_:
        return "windows"
    if "macos" in os_:
        return "macos"
    if "linux" in os_:
        return "linux"
    # Fall back to broad device class
    if device_type in {"mobile", "tablet"}:
        return device_type
    return "desktop"


def _primary_language(accept_language: str | None) -> str:
    if not accept_language:
        return ""
    # "en-US,en;q=0.9,es;q=0.8" → "en"
    first = accept_language.split(",")[0].strip()
    return first.split("-")[0].lower()


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def evaluate_condition(
    cond: Mapping[str, Any],
    *,
    user_agent: str | None,
    accept_language: str | None,
    query_params: Mapping[str, str],
    now: datetime,
) -> bool:
    kind = _norm(cond.get("type"))
    expected = cond.get("value")

    if kind == "device":
        parsed = parse_user_agent(user_agent)
        return _device_from_ua(parsed) == _norm(expected)

    if kind == "language":
        return _primary_language(accept_language) == _norm(expected)

    if kind == "browser":
        parsed = parse_user_agent(user_agent)
        return _norm(parsed.get("browser")) == _norm(expected)

    if kind == "query_param":
        param = cond.get("param") or cond.get("name")
        if not param:
            return False
        actual = query_params.get(param)
        if expected is None:
            return actual is not None  # presence-only match
        return _norm(actual) == _norm(expected)

    if kind == "before_date":
        target = _parse_iso(str(expected))
        return target is not None and now < target

    if kind == "after_date":
        target = _parse_iso(str(expected))
        return target is not None and now >= target

    return False  # unknown type — fail closed


def rule_matches(
    rule_conditions: list[dict] | None,
    *,
    user_agent: str | None,
    accept_language: str | None,
    query_params: Mapping[str, str],
    now: datetime | None = None,
) -> bool:
    """All conditions must match (AND). Empty list never matches."""
    if not rule_conditions:
        return False
    when = now or datetime.now(timezone.utc)
    return all(
        evaluate_condition(
            cond,
            user_agent=user_agent,
            accept_language=accept_language,
            query_params=query_params,
            now=when,
        )
        for cond in rule_conditions
    )


def pick_target(
    rules: list,
    default_url: str,
    *,
    user_agent: str | None,
    accept_language: str | None,
    query_params: Mapping[str, str],
    now: datetime | None = None,
) -> str:
    """First matching rule wins; otherwise the URL's default destination."""
    when = now or datetime.now(timezone.utc)
    for rule in sorted(rules, key=lambda r: r.priority):
        if rule_matches(
            rule.conditions,
            user_agent=user_agent,
            accept_language=accept_language,
            query_params=query_params,
            now=when,
        ):
            return rule.target_url
    return default_url
