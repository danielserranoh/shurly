"""Campaign management endpoints."""

import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import URL, Campaign, User
from server.schemas.campaign import (
    CampaignCreate,
    CampaignListResponse,
    CampaignResponse,
    CampaignURLResponse,
)
from server.schemas.responses import get_responses
from server.utils.campaign import generate_campaign_urls, parse_csv, validate_csv

campaigns_router = APIRouter()


def build_short_url(short_code: str) -> str:
    """Build the full short URL from a short code."""
    # For now, use localhost. In production, this would be settings.base_url
    base_url = "http://localhost:8000"
    return f"{base_url}/{short_code}"


@campaigns_router.post(
    "",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Campaign created successfully"},
        **get_responses(400, 401, 422, 500),
    },
)
def create_campaign(
    campaign_data: CampaignCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a campaign with bulk URL creation from CSV.

    Generates multiple personalized short URLs from CSV data.

    **Authentication:** Required (JWT Bearer token)

    **Request Body:**
    - **name**: Campaign name (required)
    - **original_url**: Base URL that all short URLs will redirect to (required)
    - **csv_data**: CSV string with header row and data rows (required)

    **CSV Format:**
    The CSV should have a header row defining column names, followed by data rows.
    Each row will generate one short URL with the row data as query parameters.

    Example CSV:
    ```
    firstName,lastName,company
    John,Doe,Acme
    Jane,Smith,TechCorp
    ```

    This creates 2 short URLs, each redirecting to original_url with the row's data as query params.

    **Responses:**
    - **201**: Campaign created successfully - Returns campaign details with URL count
    - **400**: CSV parsing or validation error (empty CSV, inconsistent columns, etc.)
    - **401**: Authentication required or invalid token
    - **422**: Validation error (invalid URL format, missing fields, etc.)
    - **500**: Failed to generate unique short codes for all URLs
    """
    # Parse CSV
    try:
        rows = parse_csv(campaign_data.csv_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV parsing error: {str(e)}",
        ) from e

    # Validate CSV
    is_valid, column_names, error_msg = validate_csv(rows)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"CSV validation error: {error_msg}",
        )

    # Create campaign record
    campaign = Campaign(
        name=campaign_data.name,
        original_url=campaign_data.original_url,
        csv_columns=column_names,
        created_by=current_user.id,
    )

    db.add(campaign)
    db.flush()  # Get campaign.id without committing yet

    # Generate URLs for each CSV row
    try:
        urls = generate_campaign_urls(
            campaign_id=campaign.id,
            rows=rows,
            original_url=campaign_data.original_url,
            created_by=current_user.id,
            db_session=db,
        )
    except RuntimeError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e

    # Add all URLs to session
    db.add_all(urls)
    db.commit()
    db.refresh(campaign)

    # Build response
    response = CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        original_url=campaign.original_url,
        csv_columns=campaign.csv_columns,
        url_count=len(urls),
        created_at=campaign.created_at,
    )

    return response


@campaigns_router.get(
    "",
    response_model=CampaignListResponse,
    responses={
        200: {"description": "List of campaigns retrieved successfully"},
        **get_responses(401),
    },
)
def list_campaigns(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
):
    """
    List all campaigns created by the current user.

    Returns a paginated list of all campaigns with their URL counts.

    **Authentication:** Required (JWT Bearer token)

    **Query Parameters:**
    - **skip**: Number of records to skip for pagination (default: 0)
    - **limit**: Maximum number of records to return (default: 100, max: 100)

    **Responses:**
    - **200**: List of campaigns retrieved successfully with pagination info
    - **401**: Authentication required or invalid token
    """
    campaigns = (
        db.query(Campaign)
        .filter(Campaign.created_by == current_user.id)
        .order_by(Campaign.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    total = db.query(Campaign).filter(Campaign.created_by == current_user.id).count()

    # Build responses with URL counts
    campaign_responses = []
    for campaign in campaigns:
        url_count = db.query(URL).filter(URL.campaign_id == campaign.id).count()
        response = CampaignResponse(
            id=campaign.id,
            name=campaign.name,
            original_url=campaign.original_url,
            csv_columns=campaign.csv_columns,
            url_count=url_count,
            created_at=campaign.created_at,
        )
        campaign_responses.append(response)

    return CampaignListResponse(campaigns=campaign_responses, total=total)


@campaigns_router.get(
    "/{campaign_id}",
    response_model=CampaignResponse,
    responses={
        200: {"description": "Campaign details retrieved successfully"},
        **get_responses(400, 401, 403, 404),
    },
)
def get_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get campaign details with all associated URLs.

    Returns complete campaign information including all generated short URLs.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **campaign_id**: UUID of the campaign

    **Responses:**
    - **200**: Campaign details retrieved successfully - Includes all URLs with user data
    - **400**: Invalid campaign ID format (not a valid UUID)
    - **401**: Authentication required or invalid token
    - **403**: You don't have permission to access this campaign
    - **404**: Campaign not found
    """
    # Convert string to UUID
    try:
        uuid_id = UUID(campaign_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format",
        ) from e

    campaign = db.query(Campaign).filter(Campaign.id == uuid_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found",
        )

    # Check ownership
    if campaign.created_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this campaign",
        )

    # Get all URLs for this campaign
    urls = db.query(URL).filter(URL.campaign_id == campaign.id).all()

    # Build URL responses
    url_responses = []
    for url in urls:
        url_response = CampaignURLResponse.model_validate(url)
        url_response.short_url = build_short_url(url.short_code)
        url_responses.append(url_response)

    # Build campaign response
    response = CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        original_url=campaign.original_url,
        csv_columns=campaign.csv_columns,
        url_count=len(urls),
        created_at=campaign.created_at,
        urls=url_responses,
    )

    return response


@campaigns_router.get(
    "/{campaign_id}/export",
    responses={
        200: {"description": "CSV file download", "content": {"text/csv": {}}},
        **get_responses(400, 401, 403, 404),
    },
)
def export_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export campaign URLs as CSV.

    Downloads a CSV file containing all campaign URLs and their associated user data.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **campaign_id**: UUID of the campaign

    **Responses:**
    - **200**: CSV file download - Includes short_code, short_url, original_url, and all user data columns
    - **400**: Invalid campaign ID format (not a valid UUID)
    - **401**: Authentication required or invalid token
    - **403**: You don't have permission to access this campaign
    - **404**: Campaign not found or no URLs in campaign

    **Note:** The CSV filename will be `campaign_{name}.csv`
    """
    # Convert string to UUID
    try:
        uuid_id = UUID(campaign_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format",
        ) from e

    campaign = db.query(Campaign).filter(Campaign.id == uuid_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found",
        )

    # Check ownership
    if campaign.created_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to access this campaign",
        )

    # Get all URLs for this campaign
    urls = db.query(URL).filter(URL.campaign_id == campaign.id).all()

    if not urls:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No URLs found for this campaign",
        )

    # Build CSV
    output = io.StringIO()

    # Determine all columns: short_code, short_url, original_url, + user_data keys
    user_data_columns = campaign.csv_columns
    fieldnames = ["short_code", "short_url", "original_url"] + user_data_columns

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for url in urls:
        row = {
            "short_code": url.short_code,
            "short_url": build_short_url(url.short_code),
            "original_url": url.original_url,
        }
        # Add user_data fields
        if url.user_data:
            for key in user_data_columns:
                row[key] = url.user_data.get(key, "")

        writer.writerow(row)

    # Return CSV as downloadable file
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=campaign_{campaign.name}.csv"},
    )


@campaigns_router.delete(
    "/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Campaign deleted successfully"},
        **get_responses(400, 401, 403, 404),
    },
)
def delete_campaign(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a campaign and all associated URLs.

    Removes the campaign and all its generated short URLs (cascade delete).

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **campaign_id**: UUID of the campaign

    **Responses:**
    - **204**: Campaign deleted successfully (no content returned)
    - **400**: Invalid campaign ID format (not a valid UUID)
    - **401**: Authentication required or invalid token
    - **403**: You don't have permission to delete this campaign
    - **404**: Campaign not found

    **Warning:** This will cascade delete all URLs and analytics data for this campaign.
    """
    # Convert string to UUID
    try:
        uuid_id = UUID(campaign_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format",
        ) from e

    campaign = db.query(Campaign).filter(Campaign.id == uuid_id).first()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found",
        )

    # Check ownership
    if campaign.created_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this campaign",
        )

    # Delete campaign (cascades to URLs)
    db.delete(campaign)
    db.commit()

    return None
