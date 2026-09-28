"""Phase 3.12 — profile schemas. The rules for each field live in server/utils/profile.py."""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from server.utils.profile import NAME_MAX_LENGTH, clean_country, clean_name, clean_timezone

COUNTRY = "ISO 3166-1 alpha-2 country code, e.g. ES."
TIMEZONE = "IANA time zone, e.g. Europe/Madrid, never an offset."

Name = Annotated[
    Annotated[str, StringConstraints(max_length=NAME_MAX_LENGTH)] | None,
    BeforeValidator(clean_name),
]
Country = Annotated[str | None, BeforeValidator(clean_country)]
Timezone = Annotated[str | None, BeforeValidator(clean_timezone)]


class ProfileResponse(BaseModel):
    """The profile. A field is null until the person sets it."""

    model_config = ConfigDict(from_attributes=True)

    first_name: str | None = None
    last_name: str | None = None
    country: str | None = Field(None, description=COUNTRY)
    timezone: str | None = Field(None, description=TIMEZONE)


class ProfileUpdate(BaseModel):
    """PATCH /auth/me/profile: only the fields sent change; null or blank clears one."""

    model_config = ConfigDict(extra="forbid")

    first_name: Name = Field(None, description="Trimmed; at most 100 characters.")
    last_name: Name = Field(None, description="Trimmed; at most 100 characters.")
    country: Country = Field(None, description=COUNTRY)
    timezone: Timezone = Field(
        None,
        description=TIMEZONE
        + " A legacy name is stored as the current one (Asia/Calcutta → Asia/Kolkata).",
    )
