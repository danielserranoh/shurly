"""
Phase 6.1 — who the fake Google of tests/e2e/app.py signs in: the owner, the
organization's first account, unless the browser carries the cookie
`e2e_as=member`. Then it's a second account on the same Workspace domain, which
joins as a member (join_default_organization). frontend/e2e/member.setup.ts sets
the cookie, and env.ts has the same names.

A module of its own, with no app in it, so tests/test_e2e_guard.py can check the
choice without building the app.
"""

OWNER = "e2e.owner@griddo.io"
MEMBER = "e2e.member@griddo.io"
COOKIE = "e2e_as"

_IDENTITIES = {
    "owner": {"email": OWNER, "sub": "e2e-owner"},
    "member": {"email": MEMBER, "sub": "e2e-member"},
}


def identity(cookie: str | None) -> dict[str, str]:
    """The claims a sign-in gets: the owner's without the cookie. A name the harness
    doesn't know is a KeyError, never the owner by mistake."""
    return dict(_IDENTITIES[cookie or "owner"])
