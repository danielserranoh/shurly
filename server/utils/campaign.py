"""Utilities for campaign management."""

import csv
import io
from uuid import UUID

from server.core.models import URL, URLType
from server.utils.url import generate_short_code


def parse_csv(csv_data: str) -> list[dict]:
    """
    Parse CSV data and return list of row dictionaries.

    Args:
        csv_data: CSV string with header row

    Returns:
        List of dictionaries, one per row (excluding header)

    Raises:
        ValueError: If CSV is invalid or has no header
    """
    csv_data = csv_data.strip()
    if not csv_data:
        raise ValueError("CSV data is empty")

    try:
        # Use StringIO to read CSV from string
        reader = csv.DictReader(io.StringIO(csv_data))
        rows = list(reader)

        # Ensure we have a header
        if not reader.fieldnames:
            raise ValueError("CSV must have a header row")

        # Ensure we have at least one data row
        if not rows:
            raise ValueError("CSV must have at least one data row")

        return rows

    except csv.Error as e:
        raise ValueError(f"Invalid CSV format: {str(e)}") from e


def validate_csv(rows: list[dict]) -> tuple[bool, list[str], str | None]:
    """
    Validate CSV rows have consistent columns.

    Args:
        rows: List of row dictionaries from parse_csv

    Returns:
        Tuple of (is_valid, column_names, error_message)
    """
    if not rows:
        return False, [], "No rows to validate"

    # Get column names from first row
    column_names = list(rows[0].keys())

    # Validate no empty column names
    if any(not col or not col.strip() for col in column_names):
        return False, [], "CSV contains empty column names"

    # Check for None values which indicate missing data from CSV parsing
    for i, row in enumerate(rows, start=2):  # Start at 2 (row 1 is header, row 2 is first data)
        # Check if any expected columns have None values (missing data)
        for col in column_names:
            if col in row and row[col] is None:
                return False, [], f"Row {i} has missing value for column '{col}'"

    return True, column_names, None


def generate_campaign_urls(
    campaign_id: UUID,
    rows: list[dict],
    original_url: str,
    created_by: UUID,
    db_session,
) -> list[URL]:
    """
    Generate URL objects for each CSV row.

    Args:
        campaign_id: UUID of the campaign
        rows: List of row dictionaries with user data
        original_url: Base URL to redirect to
        created_by: UUID of user creating the campaign
        db_session: SQLAlchemy session for checking short code uniqueness

    Returns:
        List of URL objects (not yet committed to DB)
    """
    urls = []

    for row in rows:
        # Generate unique short code
        max_attempts = 10
        short_code = None

        for _ in range(max_attempts):
            candidate = generate_short_code(length=6)
            # Check if code already exists in DB
            existing = db_session.query(URL).filter(URL.short_code == candidate).first()
            if not existing:
                short_code = candidate
                break

        if not short_code:
            raise RuntimeError("Failed to generate unique short code after multiple attempts")

        # Create URL with user data from CSV row
        url = URL(
            short_code=short_code,
            original_url=original_url,
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign_id,
            user_data=dict(row),  # Store entire row as JSON
            created_by=created_by,
        )
        urls.append(url)

    return urls
