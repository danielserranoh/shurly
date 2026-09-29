"""URL shortening endpoints."""

import base64
import hashlib
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from server.app.analytics import _exclude_bots
from server.core import get_db
from server.core.auth import get_current_user
from server.core.config import settings
from server.core.models import (
    URL,
    OrphanVisit,
    OrphanVisitType,
    RedirectRule,
    URLType,
    User,
    Visitor,
)
from server.schemas.redirect_rule import (
    RedirectRuleCreate,
    RedirectRuleResponse,
    RedirectRuleUpdate,
)
from server.schemas.responses import get_responses
from server.schemas.url import (
    OpenGraphMetadataResponse,
    URLCreate,
    URLCustomCreate,
    URLListResponse,
    URLMetadataRequest,
    URLMetadataResponse,
    URLResponse,
    URLUpdate,
)
from server.utils.access import LinkDomain, find_urls, viewer, visible_url_or_404
from server.utils.bounds import MAX_SKIP
from server.utils.columns import fit
from server.utils.domain import get_or_create_default_domain, resolve_domain_for_host
from server.utils.geo import country_of
from server.utils.negotiation import prefers_html
from server.utils.network import UNKNOWN_IP, visit_ip
from server.utils.opengraph import fetch_opengraph_metadata, is_social_media_crawler
from server.utils.redirect_rules import pick_target
from server.utils.url import (
    build_short_url,  # Phase 3.11 — moved to utils; still importable from here
    generate_short_code,
    is_reserved_short_code,
    is_valid_custom_code,
    link_hostname,
    link_short_url,
    make_code_unique,
    normalize_short_code,
    url_origin,
)
from server.utils.user_agent import is_bot as ua_is_bot

logger = logging.getLogger(__name__)

urls_router = APIRouter()
redirect_router = APIRouter()  # Separate router for redirect endpoint

# Initialize Jinja2 templates for preview page
templates = Jinja2Templates(directory="server/templates")

# ROADMAP 3.9.2 — the pages the short-link host serves come with a strict CSP: nothing but their
# one <style> block, allowed by its hash. The hash is taken from the page as it's served, so an
# edit to the CSS can't leave it unstyled; the block has no Jinja, so any render gives it.
UNAVAILABLE_PAGE = "link_unavailable.html"
PREVIEW_PAGE = "preview.html"


def _style_hash(template: str) -> str:
    served = templates.env.get_template(template).render()
    style = re.search(r"<style>(.*?)</style>", served, re.S).group(1)
    return "sha256-" + base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()


# A crawler's preview loads nothing but its style: the OG image is a meta tag the crawler fetches
# itself, and the meta refresh and the link to the destination aren't loads a CSP governs.
PREVIEW_HEADERS = {
    "Content-Security-Policy": (
        f"default-src 'none'; style-src '{_style_hash(PREVIEW_PAGE)}'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "Cache-Control": "public, max-age=300",  # 5 minutes
}


UNAVAILABLE_HEADERS = {
    "Content-Security-Policy": (
        f"default-src 'none'; style-src '{_style_hash(UNAVAILABLE_PAGE)}'; img-src data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    # A link fixed later shouldn't stay cached as a 404 or a 410.
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex",
    "Vary": "Accept",
}


def _unavailable(request: Request, status_code: int, reason: str, detail: str) -> Response:
    """
    A short link that doesn't lead anywhere: with INVALID_SHORT_URL_REDIRECT, a 302 there for
    everyone (Shlink's setting), never cached; otherwise the status code, as a page for a person's
    browser (`reason`: unknown, expired or used_up) and as the JSON it always was for everything
    else. `Vary: Accept`, since the body depends on it.
    """
    if settings.invalid_short_url_redirect:
        return RedirectResponse(
            url=settings.invalid_short_url_redirect,
            status_code=status.HTTP_302_FOUND,
            headers={"Cache-Control": "private, max-age=0"},
        )
    if not prefers_html(request.headers.get("accept")):
        raise HTTPException(status_code=status_code, detail=detail, headers={"Vary": "Accept"})
    return templates.TemplateResponse(
        request,
        UNAVAILABLE_PAGE,
        {"reason": reason},
        status_code=status_code,
        headers=UNAVAILABLE_HEADERS,
    )


# Phase 3.11 — URLResponse computed fields (`short_url`, `click_count`).


def _click_counts(db: Session, url_ids: list[UUID]) -> dict[UUID, int]:
    """
    All-time click counts for a batch of URLs, keyed by URL id.

    One grouped aggregate over `visits` regardless of batch size (no N+1). A
    "click" uses the analytics endpoints' default definition via `_exclude_bots`:
    bot/crawler hits and email tracking-pixel opens are excluded. URLs without
    clicks are absent from the returned dict.
    """
    if not url_ids:
        return {}
    rows = (
        _exclude_bots(
            db.query(Visitor.url_id, func.count(Visitor.id)).filter(Visitor.url_id.in_(url_ids)),
            include_bots=False,
        )
        .group_by(Visitor.url_id)
        .all()
    )
    return dict(rows)


def _click_count(db: Session, url: URL) -> int:
    """All-time click count for a single URL (see `_click_counts`)."""
    return _click_counts(db, [url.id]).get(url.id, 0)


def _to_url_response(url: URL, click_count: int) -> URLResponse:
    """Serialize a URL row plus its computed `short_url` and `click_count`."""
    response = URLResponse.model_validate(url)
    response.short_url = link_short_url(url)
    response.domain = link_hostname(url)
    response.click_count = click_count
    return response


@urls_router.post(
    "",
    response_model=URLResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Short URL created successfully"},
        **get_responses(401, 422, 500),
    },
)
async def create_short_url(
    url_data: URLCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a standard short URL.

    Generates a random 6-character short code and creates a shortened URL.
    Automatically fetches Open Graph metadata from the destination URL.

    **Authentication:** Required (JWT Bearer token)

    **Request Body:**
    - **url**: The original URL to shorten (must be valid http/https URL)
    - **title**: Optional user-friendly title (max 255 chars)
    - **forward_parameters**: Forward query params to destination (default: true)
    - **og_title**: Custom Open Graph title (optional)
    - **og_description**: Custom Open Graph description (optional)
    - **og_image_url**: Custom Open Graph image URL (optional)
    - **visibility**: `organization` (default) or `personal` (only you see it)

    **Responses:**
    - **201**: Short URL created successfully - Returns URL with generated 6-character code
    - **401**: Authentication required or invalid token
    - **422**: Validation error (invalid URL format)
    - **500**: Failed to generate unique short code (very rare)
    """
    # Phase 3.10.1 — bind every URL to a domain. New URLs default to the default
    # domain; multi-tenant API support comes when we expose domain selection.
    domain = get_or_create_default_domain(db)

    # Generate a unique short code (per-domain uniqueness — same code may exist
    # on a different domain row).
    max_attempts = 10
    short_code = None

    for _ in range(max_attempts):
        candidate = generate_short_code(length=6)
        existing = (
            db.query(URL).filter(URL.domain_id == domain.id, URL.short_code == candidate).first()
        )
        if not existing:
            short_code = candidate
            break

    if not short_code:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate unique short code. Please try again.",
        )

    # Auto-fetch Open Graph metadata if not provided
    og_title = url_data.og_title
    og_description = url_data.og_description
    og_image_url = url_data.og_image_url
    og_fetched_at = None

    if not (og_title or og_description or og_image_url):
        # Fetch metadata from destination URL
        metadata = await fetch_opengraph_metadata(url_data.url)
        if metadata.has_metadata():
            og_title = fit(metadata.title, URL.og_title)
            og_description = metadata.description
            og_image_url = metadata.image_url
            og_fetched_at = datetime.now(timezone.utc)

    # Create the URL
    url = URL(
        short_code=short_code,
        domain_id=domain.id,
        original_url=url_data.url,
        url_type=URLType.STANDARD,
        title=url_data.title,
        forward_parameters=url_data.forward_parameters,
        og_title=og_title,
        og_description=og_description,
        og_image_url=og_image_url,
        og_fetched_at=og_fetched_at,
        valid_since=url_data.valid_since,
        valid_until=url_data.valid_until,
        max_visits=url_data.max_visits,
        crawlable=url_data.crawlable,
        created_by=current_user.id,
        organization_id=viewer(db, current_user).organization_for(url_data.visibility),
    )

    db.add(url)
    db.commit()
    db.refresh(url)

    # Build response (a brand-new URL cannot have visits yet)
    return _to_url_response(url, click_count=0)


@urls_router.post(
    "/custom",
    response_model=URLResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Custom short URL created successfully"},
        **get_responses(400, 401, 422),
    },
)
async def create_custom_url(
    url_data: URLCustomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a custom short URL with a user-specified code.

    Allows you to specify a custom short code instead of using a random one.
    Automatically fetches Open Graph metadata from the destination URL.

    **Authentication:** Required (JWT Bearer token)

    **Request Body:**
    - **url**: The original URL to shorten (must be valid http/https URL)
    - **custom_code**: Custom short code (3-20 alphanumeric characters, hyphens, underscores)
    - **title**: Optional user-friendly title (max 255 chars)
    - **forward_parameters**: Forward query params to destination (default: true)
    - **og_title**: Custom Open Graph title (optional)
    - **og_description**: Custom Open Graph description (optional)
    - **og_image_url**: Custom Open Graph image URL (optional)
    - **visibility**: `organization` (default) or `personal` (only you see it)

    **Responses:**
    - **201**: Custom short URL created successfully - May include warning if code was modified
    - **400**: Invalid custom code format
    - **401**: Authentication required or invalid token
    - **422**: Validation error (invalid URL format)
    - **500**: Failed to find a free variant of a taken code (very rare)

    **Note:** If the custom code is already taken, or reserved because Shurly serves that
    path itself (`mcp`, `docs`, `redoc`), random characters will be appended and a warning returned.
    """
    # Validate custom code
    if not is_valid_custom_code(url_data.custom_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid custom code. Must be 3-20 characters (alphanumeric, hyphens, underscores only).",
        )

    # Phase 3.9.6 — apply SHORT_URL_MODE to user-supplied slugs.
    requested_code = normalize_short_code(url_data.custom_code)
    short_code = requested_code
    warning = None

    # Phase 3.10.1 — uniqueness is per-domain; check inside the default domain.
    domain = get_or_create_default_domain(db)

    def is_unavailable(code: str) -> bool:
        # Reserved codes (/mcp, /docs, …) are paths the app serves itself, so a
        # short link there could never resolve: treat them as taken.
        if is_reserved_short_code(code):
            return True
        return (
            db.query(URL).filter(URL.domain_id == domain.id, URL.short_code == code).first()
            is not None
        )

    if is_unavailable(requested_code):
        # Append random characters until the code is free. Built from the
        # normalized code so loose mode stays lowercase, and re-checked because
        # the suffixed code can be taken too.
        short_code = None
        for _ in range(10):
            candidate = make_code_unique(requested_code, append_length=3)
            if not is_unavailable(candidate):
                short_code = candidate
                break

        if not short_code:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate unique short code. Please try again.",
            )

        reason = "is reserved" if is_reserved_short_code(requested_code) else "was already taken"
        warning = (
            f"The requested code '{url_data.custom_code}' {reason}. Modified to '{short_code}'."
        )

    # Auto-fetch Open Graph metadata if not provided
    og_title = url_data.og_title
    og_description = url_data.og_description
    og_image_url = url_data.og_image_url
    og_fetched_at = None

    if not (og_title or og_description or og_image_url):
        # Fetch metadata from destination URL
        metadata = await fetch_opengraph_metadata(url_data.url)
        if metadata.has_metadata():
            og_title = fit(metadata.title, URL.og_title)
            og_description = metadata.description
            og_image_url = metadata.image_url
            og_fetched_at = datetime.now(timezone.utc)

    # Create the URL
    url = URL(
        short_code=short_code,
        domain_id=domain.id,
        original_url=url_data.url,
        url_type=URLType.CUSTOM,
        title=url_data.title,
        forward_parameters=url_data.forward_parameters,
        og_title=og_title,
        og_description=og_description,
        og_image_url=og_image_url,
        og_fetched_at=og_fetched_at,
        valid_since=url_data.valid_since,
        valid_until=url_data.valid_until,
        max_visits=url_data.max_visits,
        crawlable=url_data.crawlable,
        created_by=current_user.id,
        organization_id=viewer(db, current_user).organization_for(url_data.visibility),
    )

    db.add(url)
    db.commit()
    db.refresh(url)

    # Build response (a brand-new URL cannot have visits yet)
    response = _to_url_response(url, click_count=0)
    response.warning = warning

    return response


@urls_router.post(
    "/fetch-metadata",
    response_model=URLMetadataResponse,
    responses={
        200: {"description": "Open Graph metadata fetched (fields are null when unavailable)"},
        **get_responses(401, 422),
    },
)
async def fetch_url_metadata(
    url_data: URLMetadataRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Fetch Open Graph metadata for a destination URL without creating a short URL.

    Phase 3.11 — lets the UI render a live link preview while the create form is
    still being filled in. Nothing is persisted.

    **Authentication:** Required (JWT Bearer token)

    **Request Body:**
    - **url**: Destination URL to inspect (must be a valid http/https URL)

    **Responses:**
    - **200**: Metadata returned - `og_title`, `og_description`, `og_image_url` (each null when the page has none or the fetch fails / times out)
    - **401**: Authentication required or invalid token
    - **422**: Validation error (invalid URL format)

    **Note:** Upstream failures never surface as errors; they yield all-null fields.
    """
    try:
        metadata = await fetch_opengraph_metadata(url_data.url)
    except Exception:
        # fetch_opengraph_metadata already swallows network/parse errors; this guard
        # keeps the "never 500" contract even if the fetcher's behaviour changes.
        logger.warning("Open Graph lookup failed for %s", url_origin(url_data.url), exc_info=True)
        return URLMetadataResponse()

    return URLMetadataResponse(
        og_title=fit(metadata.title, URL.og_title),
        og_description=metadata.description,
        og_image_url=metadata.image_url,
    )


@urls_router.get(
    "",
    response_model=URLListResponse,
    responses={
        200: {"description": "List of URLs retrieved successfully"},
        **get_responses(400, 401, 422),
    },
)
def list_urls(
    tags: str | None = Query(None, description="Comma-separated tag IDs to filter by"),
    tag_filter: str = Query("any", description="'all' (AND) or 'any' (OR) for multiple tags"),
    q: str | None = Query(
        None,
        description="Case-insensitive substring match on title, destination URL or short code",
    ),
    url_type: list[URLType] | None = Query(
        None,
        description="Only return URLs of these types (standard, custom, campaign). Repeat the "
        "parameter to match any of several, e.g. ?url_type=standard&url_type=custom",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = Query(0, ge=0, le=MAX_SKIP, description="Number of URLs to skip, for pagination"),
    limit: int = Query(100, ge=1, le=100, description="Maximum number of URLs to return (1-100)"),
):
    """
    List the URLs the current user can see: the organization's and their own personal ones.

    Returns a paginated list of all shortened URLs (standard, custom, and campaign),
    newest first. Filters are optional and combine with AND; `total` counts every
    URL matching the active filters (not just the returned page).

    **Authentication:** Required (JWT Bearer token)

    **Query Parameters:**
    - **skip**: Number of records to skip for pagination (default: 0, min: 0, max: 1,000,000,000)
    - **limit**: Maximum number of records to return (default: 100, min: 1, max: 100).
      Out-of-range values are rejected with 422, not clamped: to read more than 100
      URLs, page through them with `skip` until you have `total`.
    - **tags**: Comma-separated tag IDs to filter by
    - **tag_filter**: 'all' (AND) or 'any' (OR) for multiple tags (default: 'any')
    - **q**: Case-insensitive substring search over title, destination URL and short code (`%` and `_` match literally; surrounding whitespace is ignored)
    - **url_type**: Only return `standard`, `custom` or `campaign` URLs; repeat it to match several types

    Each item includes `click_count`: all-time clicks excluding bots and email tracking-pixel opens.

    **Responses:**
    - **200**: List of URLs retrieved successfully with pagination info
    - **400**: Invalid tag ID format
    - **401**: Authentication required or invalid token
    - **422**: Validation error (invalid `url_type`, or `skip` / `limit` out of range)
    """
    from server.core.models import Tag

    query = db.query(URL).filter(viewer(db, current_user).sees(URL))

    # Apply tag filtering
    if tags:
        tag_ids_str = [t.strip() for t in tags.split(",")]

        # Convert string UUIDs to UUID objects
        try:
            tag_ids = [UUID(tid) for tid in tag_ids_str]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid tag ID format: {str(e)}") from e

        if tag_filter == "all":
            # AND logic: URL must have ALL tags
            for tag_id in tag_ids:
                query = query.filter(URL.tags.any(Tag.id == tag_id))
        else:
            # OR logic: URL must have ANY tag
            query = query.filter(URL.tags.any(Tag.id.in_(tag_ids)))

    # Phase 3.11 — free-text search. `autoescape` makes `%` / `_` in user input match
    # literally instead of acting as LIKE wildcards.
    search = q.strip() if q else ""
    if search:
        query = query.filter(
            or_(
                URL.title.icontains(search, autoescape=True),
                URL.original_url.icontains(search, autoescape=True),
                URL.short_code.icontains(search, autoescape=True),
            )
        )

    # Phase 3.11 — URL type filter (standard / custom / campaign); repeated values OR together
    if url_type:
        query = query.filter(URL.url_type.in_(url_type))

    # Tags, creators and their profiles (Phase 3.12: names), and campaigns (their names) for
    # the whole page, one query each: no lazy load per URL, creator or campaign.
    urls = (
        query.options(
            selectinload(URL.tags),
            selectinload(URL.creator).selectinload(User.profile),
            selectinload(URL.campaign),
        )
        .order_by(URL.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = query.offset(0).limit(None).count()

    # Phase 3.11 — click counts for the whole page in one grouped query (no N+1)
    counts = _click_counts(db, [url.id for url in urls])
    url_responses = [_to_url_response(url, counts.get(url.id, 0)) for url in urls]

    return URLListResponse(urls=url_responses, total=total)


# Phase 3.11 — keep this below the static `GET ""` route. Any future static
# single-segment GET route (e.g. `/export`) must be registered ABOVE this one,
# otherwise it would be captured as a short code.
@urls_router.get(
    "/{short_code}",
    response_model=URLResponse,
    responses={
        200: {"description": "URL retrieved successfully"},
        **get_responses(401, 404),
    },
)
def get_url(
    short_code: str,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a single URL by short code.

    Returns the same shape as the list items, including the computed `short_url`
    and `click_count` (all-time clicks excluding bots and email tracking-pixel opens).

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code of the URL to retrieve

    **Responses:**
    - **200**: URL retrieved successfully
    - **401**: Authentication required or invalid token
    - **404**: URL not found, or someone else's personal link
    """
    url = visible_url_or_404(db, current_user, short_code, domain)
    return _to_url_response(url, _click_count(db, url))


@urls_router.delete(
    "/{short_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "URL deleted successfully"},
        **get_responses(400, 401, 403, 404),
    },
)
def delete_url(
    short_code: str,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a URL by short code.

    Removes the shortened URL and all associated analytics data.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code of the URL to delete

    **Responses:**
    - **204**: URL deleted successfully (no content returned)
    - **400**: Campaign URLs must be deleted through the campaign endpoint
    - **401**: Authentication required or invalid token
    - **403**: Only its creator, or an admin or owner, can change this link
    - **404**: URL not found, or someone else's personal link

    **Note:** Only standard and custom URLs can be deleted directly. Campaign URLs must be deleted through the campaign.
    """
    url = visible_url_or_404(db, current_user, short_code, domain, to_change=True)

    # Prevent deleting campaign URLs directly
    if url.url_type == URLType.CAMPAIGN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign URLs must be deleted through the campaign",
        )

    # Delete the URL (visitors will be cascade deleted if configured)
    db.delete(url)
    db.commit()

    return None


@urls_router.patch(
    "/{short_code}",
    response_model=URLResponse,
    responses={
        200: {"description": "URL updated successfully"},
        **get_responses(400, 401, 403, 404, 422),
    },
)
def update_url(
    short_code: str,
    url_update: URLUpdate,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update a URL by short code.

    Allows updating title, destination URL, forward parameters, and Open Graph metadata.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code of the URL to update

    **Request Body (all fields optional):**
    - **title**: Update URL title
    - **original_url**: Update destination URL
    - **forward_parameters**: Update forward parameters setting
    - **og_title**: Update Open Graph title
    - **og_description**: Update Open Graph description
    - **og_image_url**: Update Open Graph image URL

    **Responses:**
    - **200**: URL updated successfully
    - **400**: Campaign URLs cannot be updated
    - **401**: Authentication required or invalid token
    - **403**: Only its creator, or an admin or owner, can change this link
    - **404**: URL not found, or someone else's personal link
    - **422**: Validation error (invalid URL format)

    **Note:** The short_code itself cannot be changed. Campaign URLs must be managed through the campaign.
    """
    url = visible_url_or_404(db, current_user, short_code, domain, to_change=True)

    # Prevent updating campaign URLs
    if url.url_type == URLType.CAMPAIGN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign URLs cannot be updated individually. Update the campaign instead.",
        )

    # Update fields (only non-None values)
    update_data = url_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(url, field, value)

    db.commit()
    db.refresh(url)

    # Build response
    return _to_url_response(url, _click_count(db, url))


@urls_router.patch(
    "/{short_code}/tags",
    responses={
        200: {"description": "URL tags updated successfully"},
        **get_responses(400, 401, 403, 404),
    },
)
def update_url_tags(
    short_code: str,
    tag_data: dict,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update tags for a URL.

    Replaces all existing tags with the provided list.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code of the URL

    **Request Body:**
    - **tag_ids**: List of tag IDs to apply

    **Responses:**
    - **200**: Tags updated successfully
    - **400**: One or more tags not found
    - **401**: Authentication required or invalid token
    - **403**: Only its creator, or an admin or owner, can change this link
    - **404**: URL not found, or someone else's personal link
    """
    from server.core.models import Tag

    url = visible_url_or_404(db, current_user, short_code, domain, to_change=True)

    tag_ids_str = tag_data.get("tag_ids", [])

    # Convert string UUIDs to UUID objects
    from uuid import UUID

    try:
        tag_ids = [UUID(str(tid)) for tid in tag_ids_str]
    except (ValueError, AttributeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid tag ID format: {str(e)}") from e

    # Validate tag IDs exist
    tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()
    if len(tags) != len(tag_ids):
        raise HTTPException(status_code=400, detail="One or more tags not found")

    # Replace tags
    url.tags = tags
    db.commit()
    db.refresh(url)

    # Build response
    from server.schemas.tag import TagResponse

    return {
        "short_code": url.short_code,
        "tags": [TagResponse.model_validate(tag) for tag in url.tags],
    }


@urls_router.post(
    "/bulk/tags",
    responses={
        200: {"description": "Bulk tagging completed"},
        **get_responses(400, 401),
    },
)
def bulk_tag_urls(
    bulk_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Apply tags to multiple URLs.

    Adds tags to the specified URLs (doesn't replace existing tags).

    **Authentication:** Required (JWT Bearer token)

    **Request Body:**
    - **links**: The links to tag, each `{"short_code": …, "domain": …}`. Use `links` when
      codes exist on several domains: the domain picks the link
    - **short_codes**: Short codes to tag, one link per code: the default domain's, then
      the other domains' by hostname (as without `?domain=`)
    - **tag_ids**: List of tag IDs to apply

    **Responses:**
    - **200**: Bulk tagging completed with success count; links you can see but not
      change are listed in `failed`
    - **400**: One or more tags not found
    - **401**: Authentication required or invalid token
    """
    from server.core.models import Tag

    # Phase 8.3 — a link is its code and its domain: `links` name both; a plain code takes
    # one link, by the same rule as a route without `?domain=` (`find_url`).
    addresses = [
        (item.get("short_code"), item.get("domain")) for item in bulk_data.get("links", [])
    ]
    addresses += [(code, None) for code in bulk_data.get("short_codes", [])]
    tag_ids_str = bulk_data.get("tag_ids", [])

    # Convert string UUIDs to UUID objects
    from uuid import UUID

    try:
        tag_ids = [UUID(str(tid)) for tid in tag_ids_str]
    except (ValueError, AttributeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid tag ID format: {str(e)}") from e

    # The links the user can see, each once, with their current tags in one query (no N+1)
    who = viewer(db, current_user)
    addresses = [(code, domain) for code, domain in addresses if isinstance(code, str)]
    found = find_urls(db, who, addresses, selectinload(URL.tags))
    urls = list({url.id: url for url in found.values()}.values())

    # Fetch tags
    tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()
    if len(tags) != len(tag_ids):
        raise HTTPException(status_code=400, detail="One or more tags not found")

    updated = 0
    failed = []

    for url in urls:
        if not who.can_change(url):
            failed.append(
                {"short_code": url.short_code, "error": "Not allowed to change this link"}
            )
            continue
        try:
            # Add tags (don't replace, add to existing)
            for tag in tags:
                if tag not in url.tags:
                    url.tags.append(tag)
            updated += 1
        except Exception as e:
            failed.append({"short_code": url.short_code, "error": str(e)})

    db.commit()

    return {"updated": updated, "failed": failed}


@urls_router.get(
    "/{short_code}/preview",
    response_model=OpenGraphMetadataResponse,
    responses={
        200: {"description": "Open Graph preview metadata retrieved"},
        **get_responses(401, 404),
    },
)
def get_url_preview(
    short_code: str,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get Open Graph preview metadata for a URL.

    Returns the current Open Graph metadata for social media previews.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code to get preview metadata for

    **Responses:**
    - **200**: Preview metadata retrieved successfully
    - **401**: Authentication required or invalid token
    - **404**: URL not found, or someone else's personal link
    """
    url = visible_url_or_404(db, current_user, short_code, domain)

    has_custom = bool(url.og_title or url.og_description or url.og_image_url)

    return OpenGraphMetadataResponse(
        og_title=url.og_title or url.title,
        og_description=url.og_description,
        og_image_url=url.og_image_url,
        og_url=link_short_url(url),
        has_custom_preview=has_custom,
        fetched_at=url.og_fetched_at,
    )


@urls_router.post(
    "/{short_code}/refresh-preview",
    response_model=OpenGraphMetadataResponse,
    responses={
        200: {"description": "Preview metadata refreshed from destination URL"},
        **get_responses(401, 403, 404),
    },
)
async def refresh_url_preview(
    short_code: str,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Refresh Open Graph metadata by fetching from destination URL.

    Re-fetches Open Graph metadata from the destination URL.
    Only updates fields that don't have custom values.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code to refresh preview metadata for

    **Responses:**
    - **200**: Preview metadata refreshed successfully
    - **401**: Authentication required or invalid token
    - **403**: Only its creator, or an admin or owner, can change this link
    - **404**: URL not found, or someone else's personal link

    **Note:** Custom Open Graph values (manually set) will not be overwritten.
    """
    url = visible_url_or_404(db, current_user, short_code, domain, to_change=True)

    # Fetch metadata from destination
    metadata = await fetch_opengraph_metadata(str(url.original_url))

    # Update URL with fetched metadata (don't override custom values)
    if metadata.has_metadata():
        if not url.og_title:  # Only update if not custom
            url.og_title = fit(metadata.title, URL.og_title)
        if not url.og_description:
            url.og_description = metadata.description
        if not url.og_image_url:
            url.og_image_url = metadata.image_url

        url.og_fetched_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(url)

    return OpenGraphMetadataResponse(
        og_title=url.og_title or url.title,
        og_description=url.og_description,
        og_image_url=url.og_image_url,
        og_url=link_short_url(url),
        has_custom_preview=bool(url.og_title or url.og_description or url.og_image_url),
        fetched_at=url.og_fetched_at,
    )


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize a possibly-naive datetime to UTC (SQLite returns naive datetimes for TZ-aware columns)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# Phase 3.14.3 — a link the user can't see is a 404; one they can see but not
# change is a 403 (server/utils/access.py).


@urls_router.get(
    "/{short_code}/rules",
    response_model=list[RedirectRuleResponse],
    responses={200: {"description": "Rules listed"}, **get_responses(401, 404)},
)
def list_redirect_rules(
    short_code: str,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    url = visible_url_or_404(db, current_user, short_code, domain)
    rules = (
        db.query(RedirectRule)
        .filter(RedirectRule.url_id == url.id)
        .order_by(RedirectRule.priority)
        .all()
    )
    return [RedirectRuleResponse.model_validate(r) for r in rules]


@urls_router.post(
    "/{short_code}/rules",
    response_model=RedirectRuleResponse,
    status_code=status.HTTP_201_CREATED,
    responses={201: {"description": "Rule created"}, **get_responses(401, 403, 404, 422)},
)
def create_redirect_rule(
    short_code: str,
    rule_data: RedirectRuleCreate,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    url = visible_url_or_404(db, current_user, short_code, domain, to_change=True)
    rule = RedirectRule(
        url_id=url.id,
        priority=rule_data.priority,
        conditions=rule_data.conditions,
        target_url=rule_data.target_url,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return RedirectRuleResponse.model_validate(rule)


@urls_router.patch(
    "/{short_code}/rules/{rule_id}",
    response_model=RedirectRuleResponse,
    responses={200: {"description": "Rule updated"}, **get_responses(401, 403, 404, 422)},
)
def update_redirect_rule(
    short_code: str,
    rule_id: str,
    rule_update: RedirectRuleUpdate,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    url = visible_url_or_404(db, current_user, short_code, domain, to_change=True)
    from uuid import UUID as _UUID

    try:
        rule_uuid = _UUID(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Rule not found") from exc
    rule = (
        db.query(RedirectRule)
        .filter(RedirectRule.id == rule_uuid, RedirectRule.url_id == url.id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    for field, value in rule_update.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return RedirectRuleResponse.model_validate(rule)


@urls_router.delete(
    "/{short_code}/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={204: {"description": "Rule deleted"}, **get_responses(401, 403, 404)},
)
def delete_redirect_rule(
    short_code: str,
    rule_id: str,
    domain: LinkDomain = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    url = visible_url_or_404(db, current_user, short_code, domain, to_change=True)
    from uuid import UUID as _UUID

    try:
        rule_uuid = _UUID(rule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Rule not found") from exc
    rule = (
        db.query(RedirectRule)
        .filter(RedirectRule.id == rule_uuid, RedirectRule.url_id == url.id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return None


# Phase 3.10.3 — 1×1 transparent GIF used as the email-open tracking pixel.
# This is the canonical 43-byte single-pixel GIF89a; embedding it in HTML emails
# triggers a GET request which we log as a Visitor row with `is_pixel=True`.
_TRANSPARENT_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
    b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01"
    b"\x00\x00\x02\x02D\x01\x00;"
)


@redirect_router.get(
    "/",
    responses={404: {"description": "Base URL has no landing page"}},
)
def base_url_landing(request: Request, db: Session = Depends(get_db)):
    """
    Phase 3.10.4 — Log direct hits to the bare base URL as orphan visits.

    Someone typed `https://shurl.griddo.io` with no code. We don't have a
    marketing landing page here (that lives on the main app), so we log the
    hit (helpful to spot leaked-without-the-code campaigns) and return 404.
    """
    db.add(
        OrphanVisit(
            type=OrphanVisitType.BASE_URL,
            attempted_path="/",
            ip=fit(visit_ip(request), OrphanVisit.ip),
            user_agent=request.headers.get("user-agent"),
            referer=request.headers.get("referer"),
        )
    )
    db.commit()
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No short code provided",
    )


@redirect_router.get(
    "/{short_code}/track",
    responses={
        200: {"description": "1x1 transparent GIF; visit logged as is_pixel=true"},
        **get_responses(404),
    },
)
def tracking_pixel(short_code: str, request: Request, db: Session = Depends(get_db)):
    """
    Phase 3.10.3 — Email open tracking pixel.

    Emits the canonical 1×1 transparent GIF with `Cache-Control: no-store` so
    every open is registered (HTML-email clients cache aggressively otherwise).
    Pixel hits are recorded on the same `visits` table with `is_pixel=True`,
    keeping the opens timeline aligned with the click timeline while letting
    analytics endpoints continue to count clicks separately.
    """
    domain = resolve_domain_for_host(db, request.headers.get("host"))
    url = db.query(URL).filter(URL.domain_id == domain.id, URL.short_code == short_code).first()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short URL '{short_code}' not found",
        )

    # Pixel hits never consume max_visits quota and are always logged (even
    # under DISABLE_TRACK_PARAM, since the whole point of the endpoint is to log).
    visit_user_agent = request.headers.get("user-agent")
    stored_ip = visit_ip(request)
    db.add(
        Visitor(
            url_id=url.id,
            short_code=short_code,
            ip=fit(stored_ip or UNKNOWN_IP, Visitor.ip),
            # Phase 8.4 — from the stored address: anonymized, when that's on.
            country=country_of(stored_ip),
            user_agent=visit_user_agent,
            referer=request.headers.get("referer"),
            is_bot=ua_is_bot(visit_user_agent),
            is_pixel=True,
        )
    )
    db.commit()

    return Response(
        content=_TRANSPARENT_GIF,
        media_type="image/gif",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@redirect_router.get(
    "/robots.txt",
    response_class=PlainTextResponse,
    responses={200: {"description": "robots.txt with default-deny short URLs policy"}},
)
def robots_txt(db: Session = Depends(get_db)) -> str:
    """
    Phase 3.9.4 — Default-deny robots.txt.

    Short URLs are not crawler-indexable unless explicitly marked `crawlable=True`.
    This protects user analytics from being polluted by indexed-page click-throughs and
    keeps short URLs out of search engines by default.
    """
    crawlable = (
        db.query(URL.short_code).filter(URL.crawlable.is_(True)).order_by(URL.short_code).all()
    )
    lines = ["User-agent: *", "Disallow: /"]
    for (code,) in crawlable:
        lines.append(f"Allow: /{code}")
    return "\n".join(lines) + "\n"


@redirect_router.get(
    "/favicon.ico", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False
)
def favicon() -> Response:
    """
    Browsers ask every host for its icon. The short-link host has none: a 204, cached a week.
    Here, and not left to `/{short_code}`, where it would be an orphan visit in "Typos & broken
    links" each time. The pages it serves say so too (`<link rel="icon" href="data:,">`).
    """
    return Response(
        status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "public, max-age=604800"}
    )


def _with_query(destination: str, params: dict) -> str:
    """`destination`, with `params` appended to its query."""
    if not params:
        return destination
    separator = "&" if "?" in destination else "?"
    return f"{destination}{separator}{urlencode(params)}"


@redirect_router.get(
    "/{short_code}",
    responses={
        302: {
            "description": "Redirect to original URL; or, with INVALID_SHORT_URL_REDIRECT, "
            "where a link that doesn't lead anywhere sends everyone"
        },
        **get_responses(404),
        410: {"description": "Short URL is expired or has reached its visit cap"},
    },
)
def redirect_short_url(short_code: str, request: Request, db: Session = Depends(get_db)):
    """
    Redirect from short URL to original URL.

    Social media crawlers see a preview page with Open Graph tags.
    Regular browsers get a direct redirect (302).

    **Path Parameters:**
    - **short_code**: The short code to redirect from

    **Responses:**
    - **200**: Preview page for social media crawlers (with Open Graph meta tags)
    - **302**: Temporary redirect to original URL for regular browsers
    - **404**: Short URL not found, or URL is not yet active (`valid_since` in the future)
    - **410**: URL is expired (`valid_until` passed) or has reached its `max_visits` cap

    A 404 or 410 is a page for a person's browser (its Accept prefers text/html), and the JSON
    `{"detail": …}` for everything else. Not yet active answers exactly as not found does. With
    INVALID_SHORT_URL_REDIRECT set, all four send everyone there instead, with a 302.

    **Note:**
    - Campaign user data is ALWAYS appended as query parameters (for personalization)
    - Regular query params are only forwarded if `forward_parameters=true` (for attribution tracking)
    - Social media crawlers (Twitter, Facebook, LinkedIn, WhatsApp, etc.) see rich preview cards
    - Only clicks use up `max_visits`, as they count in `click_count`: bot hits and tracking-pixel
      opens are logged but don't, and crawler previews aren't logged at all
    """
    # Phase 3.10.1 — resolve the URL by (Host header → domain) + short_code so
    # the same code can live on multiple hostnames. Unknown hosts fall back to
    # the default domain (single-domain at launch, but this lets new vanity
    # hosts piggyback on the same backend without a code change).
    domain = resolve_domain_for_host(db, request.headers.get("host"))
    url = db.query(URL).filter(URL.domain_id == domain.id, URL.short_code == short_code).first()

    if not url:
        # Fallback: legacy rows that pre-date Phase 3.10.1 may have NULL domain_id
        url = db.query(URL).filter(URL.domain_id.is_(None), URL.short_code == short_code).first()

    if not url:
        # Phase 3.10.4 — log the orphan before returning 404. Useful for catching
        # typo'd codes leaked into print/QR campaigns. Its IP is a visit's (`visit_ip`),
        # so the GDPR posture is the same.
        orphan_ip = visit_ip(request)
        db.add(
            OrphanVisit(
                type=OrphanVisitType.INVALID_SHORT_URL,
                attempted_path=str(request.url.path)[:2048],
                ip=fit(orphan_ip, OrphanVisit.ip),
                user_agent=request.headers.get("user-agent"),
                referer=request.headers.get("referer"),
            )
        )
        db.commit()
        return _unavailable(request, 404, "unknown", f"Short URL '{short_code}' not found")

    # Phase 3.9.2 — validity window and visit cap enforcement.
    # Order matters: not-yet-valid returns 404 (don't reveal premature URLs): it answers,
    # page included, exactly as no such code does. Expired and quota-exhausted return 410
    # (the URL existed and is no longer active).
    now = datetime.now(timezone.utc)

    if url.valid_since is not None and now < _as_utc(url.valid_since):
        return _unavailable(request, 404, "unknown", f"Short URL '{short_code}' not found")

    if url.valid_until is not None and now >= _as_utc(url.valid_until):
        return _unavailable(request, 410, "expired", "This short URL has expired")

    # The cap counts clicks, the `click_count` the API reports: bot hits and email opens don't
    # use it up. One definition, so the link page's "N of max" can't disagree with the 410.
    if url.max_visits is not None:
        if _click_count(db, url) >= url.max_visits:
            return _unavailable(
                request, 410, "used_up", "This short URL has reached its visit limit"
            )

    # Phase 3.10.2 — let conditional rules override the destination before we
    # append campaign params or forwarded query params. First-match wins by
    # priority; if no rule matches, fall through to the URL's original_url.
    destination = pick_target(
        list(url.redirect_rules),
        url.original_url,
        user_agent=request.headers.get("user-agent"),
        accept_language=request.headers.get("accept-language"),
        query_params=dict(request.query_params),
    )
    # For campaign URLs, ALWAYS append user data (personalization)
    personal = url.user_data if url.url_type == URLType.CAMPAIGN and url.user_data else {}
    # For regular query params, respect forward_parameters flag (attribution tracking)
    forwarded = dict(request.query_params) if url.forward_parameters else {}
    redirect_url = _with_query(destination, {**personal, **forwarded})

    # Check User-Agent for social media crawlers
    user_agent = request.headers.get("user-agent", "")

    if is_social_media_crawler(user_agent):
        # Serve preview page with Open Graph tags for social media. Never with the recipient's
        # data: when a recipient shares their campaign link, the social network's crawler is who
        # asks (docs/PERSONAL_DATA.md). Its refresh target is the destination as the rules pick
        # it, with what the shared address itself forwards; people get the personalized redirect.
        return templates.TemplateResponse(
            request,
            PREVIEW_PAGE,
            {
                "og_title": url.og_title or url.title or url.original_url,
                "og_description": url.og_description or f"Visit {url.original_url}",
                "og_image_url": url.og_image_url,
                # Phase 8.3 — the domain it was asked on.
                "short_url": build_short_url(short_code, domain.hostname),
                "destination_url": _with_query(destination, forwarded),
            },
            headers=PREVIEW_HEADERS,
        )

    # Phase 3.10.6 — pull configured status + cache header for each redirect path.
    cache_header = (
        f"public, max-age={settings.redirect_cache_lifetime}"
        if settings.redirect_cache_lifetime > 0
        else "private, max-age=0"
    )

    # Phase 3.9.6 — DISABLE_TRACK_PARAM: a configurable query string ("nostat" by default)
    # that suppresses Visitor logging. Used for QA / internal smoke tests so they don't
    # pollute analytics. The redirect itself still happens.
    if settings.disable_track_param in request.query_params:
        return RedirectResponse(
            url=redirect_url,
            status_code=settings.redirect_status_code,
            headers={"Cache-Control": cache_header},
        )

    # Log the visit (synchronously for now, could be background task).
    # Phase 3.9.3: classify bots at log time so analytics can default-filter them.
    # Phase 3.9.5: anonymize the IP before persisting (GDPR pseudonymization).
    # Phase 3.9.6: only honor X-Forwarded-For from trusted proxies (CIDR allowlist).
    visit_user_agent = request.headers.get("user-agent")
    stored_ip = visit_ip(request)
    visit = Visitor(
        url_id=url.id,
        short_code=short_code,
        ip=fit(stored_ip or UNKNOWN_IP, Visitor.ip),
        country=country_of(stored_ip),  # Phase 8.4 — from the stored address
        user_agent=visit_user_agent,
        referer=request.headers.get("referer"),
        is_bot=ua_is_bot(visit_user_agent),
        visited_at=now.replace(tzinfo=None),  # naive UTC, like the column's default
    )

    db.add(visit)
    # Phase 3.16 — the link's last click is a click, as `/totals` counts one: a bot's visit
    # doesn't move it, nor do a crawler's preview or a `?nostat` hit, which return above.
    if not visit.is_bot:
        url.last_click_at = now
    db.commit()

    # Phase 3.10.6 — honor REDIRECT_STATUS_CODE + REDIRECT_CACHE_LIFETIME.
    return RedirectResponse(
        url=redirect_url,
        status_code=settings.redirect_status_code,
        headers={"Cache-Control": cache_header},
    )
