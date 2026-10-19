"""Schemas for service accounts and their tokens (Phase 10.1), and their audit (10.2)."""

import ipaddress
import uuid as uuid_pkg
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.core.models.service_token import SERVICE_SCOPES
from server.schemas.datetimes import UtcDateTime

ServiceRole = Literal["member", "admin"]
# Phase 10.2 — what a token may do (`SERVICE_SCOPES`); anything else is a 422.
ServiceScope = Literal[SERVICE_SCOPES]  # type: ignore[valid-type]
# Phase 10.2 — why a token needs attention: it expires within 14 days, or nothing has used it
# for 90 days (`server/utils/service_accounts.py`, `token_warnings`).
TokenWarning = Literal["expires_soon", "unused"]
# How many allowed ranges a token takes: a short allowlist, not a firewall.
MAX_IP_RANGES = 50


class ResponsiblePerson(BaseModel):
    """The person responsible for a service account."""

    user_id: uuid_pkg.UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None


class ServiceTokenInfo(BaseModel):
    """A token, as Shurly shows it again: how it starts, never the token or its hash."""

    id: uuid_pkg.UUID
    prefix: str = Field(description="How the token starts, `shsa_<prefix>`: to tell tokens apart")
    created_at: UtcDateTime
    expires_at: UtcDateTime | None = Field(None, description="Null: it doesn't expire")
    last_used_at: UtcDateTime | None = Field(
        None, description="When it last authenticated, to the minute; null: never"
    )
    valid_until: UtcDateTime | None = Field(
        None,
        description="A renewed token's end of overlap: it works until then. Null for the active one",
    )
    # Phase 10.2 — additive: older clients ignore them.
    scopes: list[ServiceScope] = Field(
        default_factory=lambda: list(SERVICE_SCOPES), description="What the token may do"
    )
    allowed_ip_ranges: list[str] = Field(
        default_factory=list,
        description="CIDRs it may be used from; empty: any address",
    )
    warnings: list[TokenWarning] = Field(
        default_factory=list,
        description=(
            "`expires_soon`: it stops working within 14 days. `unused`: nothing has used it "
            "for 90 days. Only on the active token"
        ),
    )


class ServiceAccountResponse(BaseModel):
    id: uuid_pkg.UUID
    display_name: str
    description: str | None = None
    role: ServiceRole
    responsible: ResponsiblePerson | None = None
    created_at: UtcDateTime
    token: ServiceTokenInfo | None = Field(None, description="The active token; null: none")
    previous_token: ServiceTokenInfo | None = Field(
        None, description="The token it replaced, still working in its 24-hour overlap"
    )


class ServiceAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(..., min_length=1, max_length=255, examples=["Propuestas Griddo"])
    description: str | None = Field(None, max_length=1000)
    responsible_user_id: uuid_pkg.UUID = Field(description="A person in the organization")
    role: ServiceRole = "member"


class ServiceAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    responsible_user_id: uuid_pkg.UUID | None = None
    role: ServiceRole | None = None


class ServiceTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_at: UtcDateTime | None = Field(
        None, description="When it stops working, in the future; null: it doesn't expire"
    )
    # Phase 10.2 — both optional. Left out: a first token gets every scope and any address, a
    # renewal keeps the ones of the token it replaces.
    scopes: list[ServiceScope] | None = Field(
        None,
        min_length=1,
        description=(
            "What the token may do, at least one. Left out or null: every scope for a first "
            "token, the replaced token's for a renewal"
        ),
        examples=[["urls:read", "urls:write", "act_on_behalf"]],
    )
    allowed_ip_ranges: list[str] | None = Field(
        None,
        max_length=MAX_IP_RANGES,
        description=(
            "CIDRs (IPv4 or IPv6) it may be used from; empty or null: any address. Left out: "
            "any address for a first token, the replaced token's for a renewal"
        ),
        examples=[["203.0.113.0/24", "2001:db8::/32"]],
    )

    @field_validator("scopes")
    @classmethod
    def _dedupe_scopes(cls, value: list[str] | None) -> list[str] | None:
        """Each scope once, in `SERVICE_SCOPES`' order."""
        if value is None:
            return None
        return [scope for scope in SERVICE_SCOPES if scope in value]

    @field_validator("allowed_ip_ranges")
    @classmethod
    def _normalize_ranges(cls, value: list[str] | None) -> list[str] | None:
        """Each range as its network (`10.1.2.3/24` → `10.1.2.0/24`), once, in the order sent."""
        if value is None:
            return None
        ranges: list[str] = []
        for raw in value:
            try:
                network = str(ipaddress.ip_network(raw.strip(), strict=False))
            except ValueError:
                raise ValueError(
                    f"{raw!r} isn't an IP range (CIDR), such as 203.0.113.0/24"
                ) from None
            if network not in ranges:
                ranges.append(network)
        return ranges

    def settings_sent(self) -> dict:
        """The 10.2 settings the request set, null included: those a renewal doesn't inherit."""
        sent = {}
        if self.scopes is not None:
            sent["scopes"] = self.scopes
        if "allowed_ip_ranges" in self.model_fields_set:
            sent["allowed_ip_ranges"] = self.allowed_ip_ranges or None
        return sent


class ServiceTokenIssued(ServiceTokenInfo):
    """A new token: the secret, this once. Shurly keeps only its hash."""

    token: str = Field(description="`shsa_<prefix>_<secret>`. Shown only now: keep it safe")
    renewed: bool = Field(description="It replaced a token, which keeps working for 24 hours")
    service_account: ServiceAccountResponse


# ---------------------------------------------------------------- The audit (Phase 10.2)


class AuditPerson(BaseModel):
    """A person named in the audit, as they are now: someone deleted keeps only the id."""

    id: uuid_pkg.UUID
    email: str | None = None
    name: str | None = Field(None, description="First and last name, from their profile")
    deleted: bool = Field(False, description="They no longer exist: only the id is left")


class AuditServiceAccount(BaseModel):
    id: uuid_pkg.UUID
    display_name: str | None = None
    deleted: bool = False


class AuditEventItem(BaseModel):
    id: uuid_pkg.UUID
    at: UtcDateTime
    action: str = Field(examples=["url.created", "service_token.renewed"])
    target_type: str = Field(examples=["url", "campaign", "service_token"])
    target_id: str | None = None
    short_code: str | None = Field(
        None, description="For a link: its short code, while it exists and the reader sees it"
    )
    detail: dict | None = Field(None, description="Ids and the names of fields, never values")
    service_account: AuditServiceAccount
    token_id: uuid_pkg.UUID | None = Field(None, description="The token it used, if it acted")
    actor: AuditPerson | None = Field(
        None, description="The person who made an account or token event; null: the service did"
    )
    on_behalf_of: AuditPerson | None = Field(
        None, description="The person named in X-Shurly-On-Behalf-Of; null: nobody"
    )


class AuditPage(BaseModel):
    items: list[AuditEventItem]
    next_before: UtcDateTime | None = Field(
        None, description="Pass it as `before` for the next, older page; null: no more"
    )
