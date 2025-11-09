"""URL shortening endpoints."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import URL, URLType, User, Visitor
from server.schemas.responses import get_responses
from server.schemas.url import URLCreate, URLCustomCreate, URLListResponse, URLResponse
from server.utils.url import generate_short_code, is_valid_custom_code, make_code_unique

urls_router = APIRouter()
redirect_router = APIRouter()  # Separate router for redirect endpoint


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
def create_short_url(
    url_data: URLCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a standard short URL.

    Generates a random 6-character short code and creates a shortened URL.

    **Authentication:** Required (JWT Bearer token)

    **Request Body:**
    - **url**: The original URL to shorten (must be valid http/https URL)

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

    # Create the URL
    url = URL(
        short_code=short_code,
        original_url=url_data.url,
        url_type=URLType.STANDARD,
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
def create_custom_url(
    url_data: URLCustomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a custom short URL with a user-specified code.

    Allows you to specify a custom short code instead of using a random one.

    **Authentication:** Required (JWT Bearer token)

    **Request Body:**
    - **url**: The original URL to shorten (must be valid http/https URL)
    - **custom_code**: Custom short code (3-20 alphanumeric characters, hyphens, underscores)

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

    short_code = url_data.custom_code
    warning = None

    # Check if code is already taken
    existing = db.query(URL).filter(URL.short_code == short_code).first()
    if existing:
        # Append random characters to make it unique
        short_code = make_code_unique(url_data.custom_code, append_length=3)
        warning = f"The requested code '{url_data.custom_code}' was already taken. Modified to '{short_code}'."

    # Create the URL
    url = URL(
        short_code=short_code,
        original_url=url_data.url,
        url_type=URLType.CUSTOM,
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

    **Responses:**
    - **200**: List of URLs retrieved successfully with pagination info
    - **401**: Authentication required or invalid token
    """
    urls = (
        db.query(URL)
        .filter(URL.created_by == current_user.id)
        .order_by(URL.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = db.query(URL).filter(URL.created_by == current_user.id).count()

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


@redirect_router.get(
    "/{short_code}",
    responses={
        302: {"description": "Redirect to original URL"},
        **get_responses(404),
    },
)
def redirect_short_url(short_code: str, request: Request, db: Session = Depends(get_db)):
    """
    Redirect from short URL to original URL.

    Performs a temporary redirect (302) to the original URL and logs the visit.

    **Path Parameters:**
    - **short_code**: The short code to redirect from

    **Responses:**
    - **302**: Temporary redirect to original URL (campaign URLs include query parameters)
    - **404**: Short URL not found

    **Note:** For campaign URLs, user data is automatically appended as query parameters.
    """
    # Find the URL
    url = db.query(URL).filter(URL.short_code == short_code).first()

    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short URL '{short_code}' not found",
        )

    # Build redirect URL
    redirect_url = url.original_url

    # For campaign URLs, append user data as query parameters
    if url.url_type == URLType.CAMPAIGN and url.user_data:
        # Build query string from user_data JSONB
        query_params = urlencode(url.user_data)
        separator = "&" if "?" in redirect_url else "?"
        redirect_url = f"{redirect_url}{separator}{query_params}"

    # Log the visit (synchronously for now, could be background task)
    visit = Visitor(
        url_id=url.id,
        short_code=short_code,
        ip=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent"),
        referer=request.headers.get("referer"),
    )

    db.add(visit)
    db.commit()

    # Redirect (302 = temporary redirect)
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
