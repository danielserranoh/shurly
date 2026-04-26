"""URL shortening endpoints."""

from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.config import settings
from server.core.models import URL, URLType, User, Visitor
from server.schemas.responses import get_responses
from server.schemas.url import (
    OpenGraphMetadataResponse,
    URLCreate,
    URLCustomCreate,
    URLListResponse,
    URLResponse,
    URLUpdate,
)
from server.utils.network import anonymize_ip, resolve_client_ip
from server.utils.opengraph import fetch_opengraph_metadata, is_social_media_crawler
from server.utils.url import (
    generate_short_code,
    is_valid_custom_code,
    make_code_unique,
    normalize_short_code,
)
from server.utils.user_agent import is_bot as ua_is_bot

urls_router = APIRouter()
redirect_router = APIRouter()  # Separate router for redirect endpoint

# Initialize Jinja2 templates for preview page
templates = Jinja2Templates(directory="server/templates")


def build_short_url(short_code: str) -> str:
    """Build the full short URL from a short code."""
    # For now, use localhost. In production, this would be settings.base_url
    base_url = "http://localhost:8000"
    return f"{base_url}/{short_code}"


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

    **Responses:**
    - **201**: Short URL created successfully - Returns URL with generated 6-character code
    - **401**: Authentication required or invalid token
    - **422**: Validation error (invalid URL format)
    - **500**: Failed to generate unique short code (very rare)
    """
    # Generate a unique short code
    max_attempts = 10
    short_code = None

    for _ in range(max_attempts):
        candidate = generate_short_code(length=6)
        existing = db.query(URL).filter(URL.short_code == candidate).first()
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
            og_title = metadata.title
            og_description = metadata.description
            og_image_url = metadata.image_url
            og_fetched_at = datetime.now(timezone.utc)

    # Create the URL
    url = URL(
        short_code=short_code,
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
    )

    db.add(url)
    db.commit()
    db.refresh(url)

    # Build response
    response = URLResponse.model_validate(url)
    response.short_url = build_short_url(url.short_code)

    return response


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

    **Responses:**
    - **201**: Custom short URL created successfully - May include warning if code was modified
    - **400**: Invalid custom code format
    - **401**: Authentication required or invalid token
    - **422**: Validation error (invalid URL format)

    **Note:** If the custom code is already taken, random characters will be appended and a warning returned.
    """
    # Validate custom code
    if not is_valid_custom_code(url_data.custom_code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid custom code. Must be 3-20 characters (alphanumeric, hyphens, underscores only).",
        )

    # Phase 3.9.6 — apply SHORT_URL_MODE to user-supplied slugs.
    short_code = normalize_short_code(url_data.custom_code)
    warning = None

    # Check if code is already taken
    existing = db.query(URL).filter(URL.short_code == short_code).first()
    if existing:
        # Append random characters to make it unique
        short_code = make_code_unique(url_data.custom_code, append_length=3)
        warning = f"The requested code '{url_data.custom_code}' was already taken. Modified to '{short_code}'."

    # Auto-fetch Open Graph metadata if not provided
    og_title = url_data.og_title
    og_description = url_data.og_description
    og_image_url = url_data.og_image_url
    og_fetched_at = None

    if not (og_title or og_description or og_image_url):
        # Fetch metadata from destination URL
        metadata = await fetch_opengraph_metadata(url_data.url)
        if metadata.has_metadata():
            og_title = metadata.title
            og_description = metadata.description
            og_image_url = metadata.image_url
            og_fetched_at = datetime.now(timezone.utc)

    # Create the URL
    url = URL(
        short_code=short_code,
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
    )

    db.add(url)
    db.commit()
    db.refresh(url)

    # Build response
    response = URLResponse.model_validate(url)
    response.short_url = build_short_url(url.short_code)
    response.warning = warning

    return response


@urls_router.get(
    "",
    response_model=URLListResponse,
    responses={
        200: {"description": "List of URLs retrieved successfully"},
        **get_responses(401),
    },
)
def list_urls(
    tags: str | None = Query(None, description="Comma-separated tag IDs to filter by"),
    tag_filter: str = Query("any", description="'all' (AND) or 'any' (OR) for multiple tags"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
):
    """
    List all URLs created by the current user.

    Returns a paginated list of all shortened URLs (standard, custom, and campaign).

    **Authentication:** Required (JWT Bearer token)

    **Query Parameters:**
    - **skip**: Number of records to skip for pagination (default: 0)
    - **limit**: Maximum number of records to return (default: 100, max: 100)
    - **tags**: Comma-separated tag IDs to filter by
    - **tag_filter**: 'all' (AND) or 'any' (OR) for multiple tags (default: 'any')

    **Responses:**
    - **200**: List of URLs retrieved successfully with pagination info
    - **401**: Authentication required or invalid token
    """
    from server.core.models import Tag

    query = db.query(URL).filter(URL.created_by == current_user.id)

    # Apply tag filtering
    if tags:
        from uuid import UUID

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

    urls = query.order_by(URL.created_at.desc()).offset(skip).limit(limit).all()

    total = query.offset(0).limit(None).count()

    # Add short_url to each URL
    url_responses = []
    for url in urls:
        response = URLResponse.model_validate(url)
        response.short_url = build_short_url(url.short_code)
        url_responses.append(response)

    return URLListResponse(urls=url_responses, total=total)


@urls_router.delete(
    "/{short_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "URL deleted successfully"},
        **get_responses(400, 401, 404),
    },
)
def delete_url(
    short_code: str,
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
    - **404**: URL not found or doesn't belong to current user

    **Note:** Only standard and custom URLs can be deleted directly. Campaign URLs must be deleted through the campaign.
    """
    # Find the URL
    url = db.query(URL).filter(URL.short_code == short_code, URL.created_by == current_user.id).first()

    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="URL not found",
        )

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
        **get_responses(400, 401, 404, 422),
    },
)
def update_url(
    short_code: str,
    url_update: URLUpdate,
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
    - **404**: URL not found or doesn't belong to current user
    - **422**: Validation error (invalid URL format)

    **Note:** The short_code itself cannot be changed. Campaign URLs must be managed through the campaign.
    """
    # Find the URL
    url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.created_by == current_user.id,
    ).first()

    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="URL not found",
        )

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
    response = URLResponse.model_validate(url)
    response.short_url = build_short_url(url.short_code)

    return response


@urls_router.patch(
    "/{short_code}/tags",
    responses={
        200: {"description": "URL tags updated successfully"},
        **get_responses(400, 401, 404),
    },
)
def update_url_tags(
    short_code: str,
    tag_data: dict,
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
    - **404**: URL not found or doesn't belong to current user
    """
    from server.core.models import Tag

    url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.created_by == current_user.id
    ).first()

    if not url:
        raise HTTPException(status_code=404, detail="URL not found")

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
        "tags": [TagResponse.model_validate(tag) for tag in url.tags]
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
    - **short_codes**: List of short codes to tag
    - **tag_ids**: List of tag IDs to apply

    **Responses:**
    - **200**: Bulk tagging completed with success count
    - **400**: One or more tags not found
    - **401**: Authentication required or invalid token
    """
    from server.core.models import Tag

    short_codes = bulk_data.get("short_codes", [])
    tag_ids_str = bulk_data.get("tag_ids", [])

    # Convert string UUIDs to UUID objects
    from uuid import UUID
    try:
        tag_ids = [UUID(str(tid)) for tid in tag_ids_str]
    except (ValueError, AttributeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid tag ID format: {str(e)}") from e

    # Fetch URLs (only user's own URLs)
    urls = db.query(URL).filter(
        URL.short_code.in_(short_codes),
        URL.created_by == current_user.id
    ).all()

    # Fetch tags
    tags = db.query(Tag).filter(Tag.id.in_(tag_ids)).all()
    if len(tags) != len(tag_ids):
        raise HTTPException(status_code=400, detail="One or more tags not found")

    updated = 0
    failed = []

    for url in urls:
        try:
            # Add tags (don't replace, add to existing)
            for tag in tags:
                if tag not in url.tags:
                    url.tags.append(tag)
            updated += 1
        except Exception as e:
            failed.append({"short_code": url.short_code, "error": str(e)})

    db.commit()

    return {
        "updated": updated,
        "failed": failed
    }


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
    - **404**: URL not found or doesn't belong to current user
    """
    url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.created_by == current_user.id,
    ).first()

    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="URL not found",
        )

    has_custom = bool(url.og_title or url.og_description or url.og_image_url)

    return OpenGraphMetadataResponse(
        og_title=url.og_title or url.title,
        og_description=url.og_description,
        og_image_url=url.og_image_url,
        og_url=build_short_url(short_code),
        has_custom_preview=has_custom,
        fetched_at=url.og_fetched_at,
    )


@urls_router.post(
    "/{short_code}/refresh-preview",
    response_model=OpenGraphMetadataResponse,
    responses={
        200: {"description": "Preview metadata refreshed from destination URL"},
        **get_responses(401, 404),
    },
)
async def refresh_url_preview(
    short_code: str,
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
    - **404**: URL not found or doesn't belong to current user

    **Note:** Custom Open Graph values (manually set) will not be overwritten.
    """
    url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.created_by == current_user.id,
    ).first()

    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="URL not found",
        )

    # Fetch metadata from destination
    metadata = await fetch_opengraph_metadata(str(url.original_url))

    # Update URL with fetched metadata (don't override custom values)
    if metadata.has_metadata():
        if not url.og_title:  # Only update if not custom
            url.og_title = metadata.title
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
        og_url=build_short_url(short_code),
        has_custom_preview=bool(url.og_title or url.og_description or url.og_image_url),
        fetched_at=url.og_fetched_at,
    )


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalize a possibly-naive datetime to UTC (SQLite returns naive datetimes for TZ-aware columns)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


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
        db.query(URL.short_code)
        .filter(URL.crawlable.is_(True))
        .order_by(URL.short_code)
        .all()
    )
    lines = ["User-agent: *", "Disallow: /"]
    for (code,) in crawlable:
        lines.append(f"Allow: /{code}")
    return "\n".join(lines) + "\n"


@redirect_router.get(
    "/{short_code}",
    responses={
        302: {"description": "Redirect to original URL"},
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

    **Note:**
    - Campaign user data is ALWAYS appended as query parameters (for personalization)
    - Regular query params are only forwarded if `forward_parameters=true` (for attribution tracking)
    - Social media crawlers (Twitter, Facebook, LinkedIn, WhatsApp, etc.) see rich preview cards
    - Crawler preview hits do NOT consume `max_visits` quota (no Visitor row inserted)
    """
    # Find the URL
    url = db.query(URL).filter(URL.short_code == short_code).first()

    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short URL '{short_code}' not found",
        )

    # Phase 3.9.2 — validity window and visit cap enforcement.
    # Order matters: not-yet-valid returns 404 (don't reveal premature URLs);
    # expired and quota-exhausted return 410 (the URL existed and is no longer active).
    now = datetime.now(timezone.utc)

    if url.valid_since is not None and now < _as_utc(url.valid_since):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short URL '{short_code}' not found",
        )

    if url.valid_until is not None and now >= _as_utc(url.valid_until):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This short URL has expired",
        )

    if url.max_visits is not None:
        visit_count = db.query(Visitor).filter(Visitor.url_id == url.id).count()
        if visit_count >= url.max_visits:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This short URL has reached its visit limit",
            )

    # Update last_click_at timestamp
    url.last_click_at = datetime.now(timezone.utc)

    # Build redirect URL
    redirect_url = url.original_url
    query_params = {}

    # For campaign URLs, ALWAYS append user data (personalization)
    if url.url_type == URLType.CAMPAIGN and url.user_data:
        query_params.update(url.user_data)

    # For regular query params, respect forward_parameters flag (attribution tracking)
    if url.forward_parameters and request.query_params:
        query_params.update(dict(request.query_params))

    # Append query params if any
    if query_params:
        query_string = urlencode(query_params)
        separator = "&" if "?" in redirect_url else "?"
        redirect_url = f"{redirect_url}{separator}{query_string}"

    # Check User-Agent for social media crawlers
    user_agent = request.headers.get("user-agent", "")

    if is_social_media_crawler(user_agent):
        # Serve preview page with Open Graph tags for social media
        return templates.TemplateResponse(
            request,
            "preview.html",
            {
                "og_title": url.og_title or url.title or url.original_url,
                "og_description": url.og_description or f"Visit {url.original_url}",
                "og_image_url": url.og_image_url,
                "short_url": build_short_url(short_code),
                "destination_url": redirect_url,
            },
            headers={"Cache-Control": "public, max-age=300"},  # Cache for 5 min
        )

    # Phase 3.9.6 — DISABLE_TRACK_PARAM: a configurable query string ("nostat" by default)
    # that suppresses Visitor logging. Used for QA / internal smoke tests so they don't
    # pollute analytics. The redirect itself still happens.
    if settings.disable_track_param in request.query_params:
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

    # Log the visit (synchronously for now, could be background task).
    # Phase 3.9.3: classify bots at log time so analytics can default-filter them.
    # Phase 3.9.5: anonymize the IP before persisting (GDPR pseudonymization).
    # Phase 3.9.6: only honor X-Forwarded-For from trusted proxies (CIDR allowlist).
    visit_user_agent = request.headers.get("user-agent")
    raw_ip = resolve_client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        settings.trusted_proxies,
    )
    stored_ip = anonymize_ip(raw_ip) if settings.anonymize_remote_addr else raw_ip
    visit = Visitor(
        url_id=url.id,
        short_code=short_code,
        ip=stored_ip or "unknown",
        user_agent=visit_user_agent,
        referer=request.headers.get("referer"),
        is_bot=ua_is_bot(visit_user_agent),
    )

    db.add(visit)
    db.commit()

    # Redirect (302 = temporary redirect) for regular browsers
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
