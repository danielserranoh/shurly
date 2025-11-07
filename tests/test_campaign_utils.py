"""Unit tests for campaign utilities."""

import pytest
from sqlalchemy.orm import Session

from server.utils.campaign import generate_campaign_urls, parse_csv, validate_csv


class TestParseCSV:
    """Test CSV parsing function."""

    def test_parse_csv_valid(self):
        """Test parsing valid CSV data."""
        csv_data = """firstName,lastName,company
John,Doe,Acme
Jane,Smith,TechCorp"""

        rows = parse_csv(csv_data)

        assert len(rows) == 2
        assert rows[0] == {"firstName": "John", "lastName": "Doe", "company": "Acme"}
        assert rows[1] == {"firstName": "Jane", "lastName": "Smith", "company": "TechCorp"}

    def test_parse_csv_with_whitespace(self):
        """Test parsing CSV with extra whitespace."""
        csv_data = """
firstName,lastName,company
John,Doe,Acme
Jane,Smith,TechCorp

"""
        rows = parse_csv(csv_data)
        assert len(rows) == 2

    def test_parse_csv_empty_raises_error(self):
        """Test that empty CSV raises error."""
        with pytest.raises(ValueError, match="CSV data is empty"):
            parse_csv("")

        with pytest.raises(ValueError, match="CSV data is empty"):
            parse_csv("   ")

    def test_parse_csv_no_data_rows_raises_error(self):
        """Test that CSV with only header raises error."""
        csv_data = "firstName,lastName,company"

        with pytest.raises(ValueError, match="must have at least one data row"):
            parse_csv(csv_data)

    def test_parse_csv_single_value(self):
        """Test parsing CSV with single value per row."""
        csv_data = """value
123
456"""

        rows = parse_csv(csv_data)
        assert len(rows) == 2
        assert rows[0] == {"value": "123"}
        assert rows[1] == {"value": "456"}

    def test_parse_csv_single_column(self):
        """Test parsing CSV with single column."""
        csv_data = """email
john@example.com
jane@example.com"""

        rows = parse_csv(csv_data)

        assert len(rows) == 2
        assert rows[0] == {"email": "john@example.com"}
        assert rows[1] == {"email": "jane@example.com"}

    def test_parse_csv_with_special_characters(self):
        """Test parsing CSV with special characters."""
        csv_data = 'name,email,notes\nJohn Doe,john@example.com,"Has special chars: @#$%"\nJane Smith,jane@example.com,Simple note'

        rows = parse_csv(csv_data)

        assert len(rows) == 2
        assert rows[0]["notes"] == "Has special chars: @#$%"
        assert rows[1]["notes"] == "Simple note"


class TestValidateCSV:
    """Test CSV validation function."""

    def test_validate_csv_valid(self):
        """Test validation of valid CSV rows."""
        rows = [
            {"firstName": "John", "lastName": "Doe"},
            {"firstName": "Jane", "lastName": "Smith"},
        ]

        is_valid, columns, error = validate_csv(rows)

        assert is_valid is True
        assert set(columns) == {"firstName", "lastName"}
        assert error is None

    def test_validate_csv_empty_rows(self):
        """Test validation of empty row list."""
        is_valid, columns, error = validate_csv([])

        assert is_valid is False
        assert columns == []
        assert "No rows to validate" in error

    def test_validate_csv_with_none_values(self):
        """Test validation fails when row has None values (missing data)."""
        # This simulates what csv.DictReader does when a row has fewer columns
        rows = [
            {"firstName": "John", "lastName": "Doe", "company": "Acme"},
            {
                "firstName": "Jane",
                "lastName": "Smith",
                "company": None,
            },  # Missing 'company' - CSV row 3
        ]

        is_valid, columns, error = validate_csv(rows)

        assert is_valid is False
        assert (
            "Row 3" in error
        )  # Second data row is CSV row 3 (row 1 is header, row 2 is first data)
        assert "missing value" in error

    def test_validate_csv_empty_column_names(self):
        """Test validation fails when column names are empty."""
        rows = [
            {"firstName": "John", "": "Doe"},
            {"firstName": "Jane", "": "Smith"},
        ]

        is_valid, columns, error = validate_csv(rows)

        assert is_valid is False
        assert "empty column names" in error

    def test_validate_csv_single_row(self):
        """Test validation works with single row."""
        rows = [{"email": "test@example.com"}]

        is_valid, columns, error = validate_csv(rows)

        assert is_valid is True
        assert columns == ["email"]
        assert error is None


class TestGenerateCampaignURLs:
    """Test bulk URL generation for campaigns."""

    def test_generate_campaign_urls(self, db_session: Session, test_user):
        """Test generating URLs for campaign rows."""
        import uuid

        campaign_id = uuid.uuid4()
        rows = [
            {"firstName": "John", "lastName": "Doe"},
            {"firstName": "Jane", "lastName": "Smith"},
        ]

        urls = generate_campaign_urls(
            campaign_id=campaign_id,
            rows=rows,
            original_url="https://example.com/landing",
            created_by=test_user.id,
            db_session=db_session,
        )

        assert len(urls) == 2

        # Check first URL
        assert urls[0].short_code is not None
        assert len(urls[0].short_code) == 6
        assert urls[0].original_url == "https://example.com/landing"
        assert urls[0].url_type.value == "campaign"
        assert urls[0].campaign_id == campaign_id
        assert urls[0].user_data == {"firstName": "John", "lastName": "Doe"}
        assert urls[0].created_by == test_user.id

        # Check second URL
        assert urls[1].short_code is not None
        assert urls[1].user_data == {"firstName": "Jane", "lastName": "Smith"}

        # Short codes should be unique
        assert urls[0].short_code != urls[1].short_code

    def test_generate_campaign_urls_empty_rows(self, db_session: Session, test_user):
        """Test generating URLs with empty row list."""
        import uuid

        urls = generate_campaign_urls(
            campaign_id=uuid.uuid4(),
            rows=[],
            original_url="https://example.com",
            created_by=test_user.id,
            db_session=db_session,
        )

        assert urls == []

    def test_generate_campaign_urls_preserves_user_data(self, db_session: Session, test_user):
        """Test that user data is preserved exactly as provided."""
        import uuid

        rows = [
            {
                "email": "test@example.com",
                "region": "EMEA",
                "tracking_id": "ABC123",
                "special_chars": "test@#$%",
            }
        ]

        urls = generate_campaign_urls(
            campaign_id=uuid.uuid4(),
            rows=rows,
            original_url="https://example.com",
            created_by=test_user.id,
            db_session=db_session,
        )

        assert len(urls) == 1
        assert urls[0].user_data == {
            "email": "test@example.com",
            "region": "EMEA",
            "tracking_id": "ABC123",
            "special_chars": "test@#$%",
        }
