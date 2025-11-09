"""Tag utility functions."""
from sqlalchemy.orm import Session

from server.core.config import settings
from server.core.models import Tag


def initialize_predefined_tags(db: Session) -> None:
    """
    Initialize predefined tags from config.
    Called on app startup or via migration.
    Idempotent - only creates missing tags.
    """
    for category, config in settings.predefined_tags.items():
        color = config["color"]
        for tag_name in config["tags"]:
            # Check if tag already exists
            existing = db.query(Tag).filter(Tag.name == tag_name.lower()).first()
            if existing:
                # Update color if changed
                if existing.color != color:
                    existing.color = color
                continue

            # Create new predefined tag
            tag = Tag(
                name=tag_name.lower(),
                display_name=tag_name,
                color=color,
                is_predefined=True,
                created_by=None
            )
            db.add(tag)

    db.commit()


def normalize_tag_name(name: str) -> str:
    """Normalize tag name to lowercase, trimmed."""
    return name.strip().lower()


def validate_tag_name(name: str) -> tuple[bool, str]:
    """
    Validate tag name.
    Returns (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Tag name cannot be empty"

    if len(name) > 30:
        return False, "Tag name cannot exceed 30 characters"

    # Check for valid characters (allow alphanumeric, spaces, hyphens, underscores, emojis)
    # Basically anything except control characters
    if any(ord(c) < 32 for c in name):
        return False, "Tag name contains invalid characters"

    return True, ""
