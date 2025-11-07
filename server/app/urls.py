"""URL shortening endpoints."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import URL, URLType, User, Visitor
from server.schemas.url import URLCreate, URLCustomCreate, URLListResponse, URLResponse
from server.utils.url import generate_short_code, is_valid_custom_code, make_code_unique

urls_router = APIRouter()
redirect_router = APIRouter()  # Separate router for redirect endpoint


def build_short_url(short_code: str) -> str:
    """Build the full short URL from a short code."""
    # For now, use localhost. In production, this would be settings.base_url
    base_url = "http://localhost:8000"
    return f"{base_url}/{short_code}"


@urls_router.post("", response_model=URLResponse, status_code=status.HTTP_201_CREATED)
def create_short_url(
    url_data: URLCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a standard short URL.

    - **url**: The original URL to shorten

    Returns a unique 6-character short code.
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


@urls_router.post("/custom", response_model=URLResponse, status_code=status.HTTP_201_CREATED)
def create_custom_url(
    url_data: URLCustomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a custom short URL with a user-specified code.

    - **url**: The original URL to shorten
    - **custom_code**: Custom short code (3-20 alphanumeric characters, hyphens, underscores)

    If the custom code is already taken, random characters will be appended and a warning returned.
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


@urls_router.get("", response_model=URLListResponse)
def list_urls(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
):
    """
    List all URLs created by the current user.

    - **skip**: Number of records to skip (for pagination)
    - **limit**: Maximum number of records to return
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


@redirect_router.get("/{short_code}")
def redirect_short_url(short_code: str, request: Request, db: Session = Depends(get_db)):
    """
    Redirect from short URL to original URL.

    For campaign URLs, user data will be appended as query parameters.
    Also logs the visit for analytics.
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
