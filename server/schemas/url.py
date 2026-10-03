"""Schemas for URL shortening."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from server.core.models.url import URLType
from server.schemas.datetimes import UtcDateTime
from server.utils.access import Visibility
from server.utils.bounds import INT4_MAX
from server.utils.previews import blank_to_none
from server.utils.url import MAX_SHORT_CODE_LENGTH, is_valid_url

if TYPE_CHECKING:
    pass  # Keep for future type checking needs

# Import for runtime use (model_rebuild needs it)
from server.schemas.tag import TagResponse  # noqa: E402


class URLCreate(BaseModel):
    """Schema for creating a standard short URL."""

    url: str = Field(..., description="The original URL to shorten")
    title: str | None = Field(None, max_length=255, description="Optional user-friendly title")
    forward_parameters: bool = Field(True, description="Forward query parameters to destination")

    # Open Graph overrides (optional). Phase 8.7 — the page's own preview is fetched either way;
    # each of these rewrites one of its fields.
    og_title: str | None = Field(
        None, max_length=255, description="Preview title, instead of the page's own"
    )
    og_description: str | None = Field(
        None, description="Preview description, instead of the page's own"
    )
    og_image_url: str | None = Field(
        None, description="Preview image URL, instead of the page's own"
    )

    # Phase 3.9.2 — validity window and visit cap (all optional, NULL = no constraint)
    valid_since: datetime | None = Field(
        None, description="URL becomes active at this UTC timestamp"
    )
    valid_until: datetime | None = Field(
        None, description="URL stops being active at this UTC timestamp"
    )
    max_visits: int | None = Field(
        None,
        ge=1,
        le=INT4_MAX,
        description="Hard cap on clicks (click_count) before returning 410 Gone",
    )

    # Phase 3.9.4 — default-deny crawlability
    crawlable: bool = Field(False, description="Allow this short URL in robots.txt (default: deny)")

    # Phase 3.14.3 — the organization's unless its creator asks for a personal one
    visibility: Visibility = Field(
        "organization",
        description="'organization' (everyone in it sees it) or 'personal' (only you do)",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v

    @field_validator("og_title", "og_description", "og_image_url", mode="before")
    @classmethod
    def blank_override_is_none(cls, v: object) -> object:
        """Phase 8.7 — an override left blank is none: the page's own value shows."""
        return blank_to_none(v)

    @field_validator("og_image_url")
    @classmethod
    def validate_og_image_url(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid image URL format. Must be a valid http or https URL.")
        return v


class URLCustomCreate(BaseModel):
    """Schema for creating a custom short URL."""

    url: str = Field(..., description="The original URL to shorten")
    custom_code: str = Field(
        ...,
        description=f"Custom short code (3-{MAX_SHORT_CODE_LENGTH} letters, numbers, hyphens or "
        "underscores)",
    )
    title: str | None = Field(None, max_length=255, description="Optional user-friendly title")
    forward_parameters: bool = Field(True, description="Forward query parameters to destination")

    # Open Graph overrides (optional). Phase 8.7 — the page's own preview is fetched either way;
    # each of these rewrites one of its fields.
    og_title: str | None = Field(
        None, max_length=255, description="Preview title, instead of the page's own"
    )
    og_description: str | None = Field(
        None, description="Preview description, instead of the page's own"
    )
    og_image_url: str | None = Field(
        None, description="Preview image URL, instead of the page's own"
    )

    # Phase 3.9.2 — validity window and visit cap
    valid_since: datetime | None = Field(
        None, description="URL becomes active at this UTC timestamp"
    )
    valid_until: datetime | None = Field(
        None, description="URL stops being active at this UTC timestamp"
    )
    max_visits: int | None = Field(
        None,
        ge=1,
        le=INT4_MAX,
        description="Hard cap on clicks (click_count) before returning 410 Gone",
    )

    # Phase 3.9.4 — default-deny crawlability
    crawlable: bool = Field(False, description="Allow this short URL in robots.txt (default: deny)")

    # Phase 3.14.3 — the organization's unless its creator asks for a personal one
    visibility: Visibility = Field(
        "organization",
        description="'organization' (everyone in it sees it) or 'personal' (only you do)",
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v

    @field_validator("og_title", "og_description", "og_image_url", mode="before")
    @classmethod
    def blank_override_is_none(cls, v: object) -> object:
        """Phase 8.7 — an override left blank is none: the page's own value shows."""
        return blank_to_none(v)

    @field_validator("og_image_url")
    @classmethod
    def validate_og_image_url(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid image URL format. Must be a valid http or https URL.")
        return v


class URLUpdate(BaseModel):
    """Schema for updating a URL."""

    title: str | None = Field(None, max_length=255, description="Update URL title")
    original_url: str | None = Field(None, description="Update destination URL")
    forward_parameters: bool | None = Field(None, description="Update forward parameters setting")

    # Open Graph overrides. Phase 8.7 — null or blank drops the override: the page's own shows.
    og_title: str | None = Field(
        None,
        max_length=255,
        description="Preview title, instead of the page's own (null or empty: the page's)",
    )
    og_description: str | None = Field(
        None,
        description="Preview description, instead of the page's own (null or empty: the page's)",
    )
    og_image_url: str | None = Field(
        None, description="Preview image URL, instead of the page's own (null or empty: the page's)"
    )

    # Phase 3.9.2 — validity window and visit cap (passing null clears the field)
    valid_since: datetime | None = Field(
        None, description="Update activation timestamp (null clears)"
    )
    valid_until: datetime | None = Field(
        None, description="Update expiration timestamp (null clears)"
    )
    max_visits: int | None = Field(
        None, ge=1, le=INT4_MAX, description="Update visit cap (null clears)"
    )

    # Phase 3.9.4 — toggle crawlability
    crawlable: bool | None = Field(None, description="Allow this short URL in robots.txt")

    @field_validator("original_url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v

    @field_validator("og_title", "og_description", "og_image_url", mode="before")
    @classmethod
    def blank_override_is_none(cls, v: object) -> object:
        """Phase 8.7 — an override left blank is none: the page's own value shows."""
        return blank_to_none(v)

    @field_validator("og_image_url")
    @classmethod
    def validate_og_image_url(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid image URL format. Must be a valid http or https URL.")
        return v

    model_config = {"extra": "forbid"}  # Prevent updating immutable fields


class URLResponse(BaseModel):
    """Schema for URL response."""

    id: UUID
    short_code: str
    short_url: str | None = None  # Computed field, set after validation
    # Phase 8.3 — the link's domain: one code can name links on several. `?domain=` on a
    # link's routes takes it. From the Domain row; set after validation for a link from
    # before domains (the default's).
    domain: str | None = None
    original_url: str
    url_type: URLType

    @field_validator("domain", mode="before")
    @classmethod
    def _hostname(cls, value: object) -> object:
        """`URL.domain` is the Domain row: its hostname."""
        return getattr(value, "hostname", value)

    title: str | None = None
    forward_parameters: bool = True

    # The social preview (Phase 8.7), in two layers. og_*: the overrides, what a person typed,
    # each null when the page's own shows. page_*: what the destination declares, from the
    # last fetch. A field's effective value is the override, else the page's.
    og_title: str | None = Field(None, description="Preview title override; null: the page's")
    og_description: str | None = Field(
        None, description="Preview description override; null: the page's"
    )
    og_image_url: str | None = Field(None, description="Preview image override; null: the page's")
    page_og_title: str | None = Field(None, description="The destination page's own title")
    page_og_description: str | None = Field(
        None, description="The destination page's own description"
    )
    page_og_image_url: str | None = Field(None, description="The destination page's own image")
    page_favicon_url: str | None = Field(None, description="The destination page's icon")
    page_fetched_at: UtcDateTime | None = Field(
        None, description="When the page_* fields were fetched; null: not yet"
    )
    has_custom_preview: bool = Field(False, description="At least one override is set")
    og_fetched_at: UtcDateTime | None = Field(
        None, description="Deprecated: the same as page_fetched_at"
    )

    # Analytics
    last_click_at: UtcDateTime | None = None
    # Phase 3.11 — all-time clicks, excluding bot/crawler hits and email tracking-pixel
    # opens (the analytics endpoints' default definition). Computed per request.
    click_count: int = 0

    # Phase 3.9.2 — validity window and visit cap
    valid_since: UtcDateTime | None = None
    valid_until: UtcDateTime | None = None
    max_visits: int | None = None

    # Phase 3.9.4 — crawlability flag
    crawlable: bool = False

    # Phase 3.11 — campaign linkage + personalization data (null for standard/custom URLs)
    campaign_id: UUID | None = None
    campaign_name: str | None = None  # its campaign's name, whichever campaign it is
    user_data: dict | None = None

    # Tags
    tags: list[TagResponse] = []

    # Audit fields
    created_at: UtcDateTime
    updated_at: UtcDateTime
    warning: str | None = None  # For custom URLs when code was modified
    # Phase 3.14.3 — whose it is
    visibility: Visibility = "organization"
    created_by_email: str | None = None
    # Phase 3.12 — the creator's name, from their profile; null without one.
    created_by_first_name: str | None = None
    created_by_last_name: str | None = None

    model_config = {"from_attributes": True}


class URLListResponse(BaseModel):
    """Schema for list of URLs."""

    urls: list[URLResponse]
    total: int


class OpenGraphMetadataResponse(BaseModel):
    """
    A link's social preview: what a share shows (Phase 8.7: each field the override, else the
    page's own), which fields are overridden, and the page's own values.
    """

    og_title: str | None = Field(
        description="The preview's title: the override, else the page's, else the link's title"
    )
    og_description: str | None = Field(
        description="The preview's description: the override, else the page's"
    )
    og_image_url: str | None = Field(
        description="The preview's image: the override, else the page's"
    )
    og_url: str
    og_title_overridden: bool = False
    og_description_overridden: bool = False
    og_image_url_overridden: bool = False
    has_custom_preview: bool = Field(
        description="At least one field is overridden: a social crawler gets Shurly's preview "
        "page; without one, the redirect, and reads the page's own tags"
    )
    page_og_title: str | None = None
    page_og_description: str | None = None
    page_og_image_url: str | None = None
    page_favicon_url: str | None = None
    fetched_at: UtcDateTime | None = Field(
        description="When the page's own values were fetched; null: not yet"
    )


class URLMetadataRequest(BaseModel):
    """Phase 3.11 — request body for a live Open Graph lookup (no link is created)."""

    url: str = Field(..., description="Destination URL to fetch Open Graph metadata from")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v


class URLMetadataResponse(BaseModel):
    """Phase 3.11 — Open Graph metadata fetched live; fields are null when unavailable."""

    og_title: str | None = None
    og_description: str | None = None
    og_image_url: str | None = None
