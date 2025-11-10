"""API endpoints for tag management."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import Tag, User
from server.core.models.tag import url_tags
from server.schemas.tag import (
    TagCreate,
    TagListResponse,
    TagResponse,
    TagUpdate,
)
from server.utils.tags import normalize_tag_name, validate_tag_name

tags_router = APIRouter(prefix="/tags", tags=["tags"])


@tags_router.get("", response_model=TagListResponse)
def list_tags(
    search: str | None = Query(None, description="Filter by name (starts-with)"),
    is_predefined: bool | None = Query(None, description="Filter by type"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all tags with optional filtering."""
    query = db.query(
        Tag,
        func.count(url_tags.c.url_id).label("usage_count")
    ).outerjoin(url_tags, Tag.id == url_tags.c.tag_id).group_by(Tag.id)

    if search:
        query = query.filter(Tag.name.startswith(search.lower()))

    if is_predefined is not None:
        query = query.filter(Tag.is_predefined == is_predefined)

    results = query.order_by(Tag.is_predefined.desc(), Tag.name).all()

    tags = [
        TagResponse(
            id=tag.id,
            name=tag.name,
            display_name=tag.display_name,
            color=tag.color,
            is_predefined=tag.is_predefined,
            usage_count=usage_count,
            created_at=tag.created_at,
        )
        for tag, usage_count in results
    ]

    return TagListResponse(tags=tags, total=len(tags))


@tags_router.post("", response_model=TagResponse, status_code=201)
def create_tag(
    tag_data: TagCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new user tag."""
    from server.core.config import settings

    # Validate
    is_valid, error = validate_tag_name(tag_data.name)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    # Normalize
    normalized = normalize_tag_name(tag_data.name)

    # Check uniqueness
    existing = db.query(Tag).filter(Tag.name == normalized).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tag already exists")

    # Create tag
    tag = Tag(
        name=normalized,
        display_name=tag_data.name.strip(),
        color=settings.user_tag_color,
        is_predefined=False,
        created_by=current_user.id,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)

    return TagResponse(
        id=tag.id,
        name=tag.name,
        display_name=tag.display_name,
        color=tag.color,
        is_predefined=tag.is_predefined,
        usage_count=0,
        created_at=tag.created_at,
    )


@tags_router.patch("/{tag_id}", response_model=TagResponse)
def update_tag(
    tag_id: str,
    tag_update: TagUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a user tag (rename only)."""
    from uuid import UUID

    # Convert string to UUID
    try:
        uuid_id = UUID(tag_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid tag ID format") from e

    tag = db.query(Tag).filter(Tag.id == uuid_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if tag.is_predefined:
        raise HTTPException(status_code=400, detail="Cannot update predefined tags")

    # Validate new name
    is_valid, error = validate_tag_name(tag_update.name)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    normalized = normalize_tag_name(tag_update.name)

    # Check uniqueness
    if normalized != tag.name:
        existing = db.query(Tag).filter(Tag.name == normalized).first()
        if existing:
            raise HTTPException(status_code=400, detail="Tag name already exists")

    # Update
    tag.name = normalized
    tag.display_name = tag_update.name.strip()
    db.commit()
    db.refresh(tag)

    # Get usage count
    usage_count = db.query(func.count(url_tags.c.url_id)).filter(
        url_tags.c.tag_id == tag.id
    ).scalar() or 0

    return TagResponse(
        id=tag.id,
        name=tag.name,
        display_name=tag.display_name,
        color=tag.color,
        is_predefined=tag.is_predefined,
        usage_count=usage_count,
        created_at=tag.created_at,
    )


@tags_router.delete("/{tag_id}", status_code=204)
def delete_tag(
    tag_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a user tag (removes from all URLs/campaigns)."""
    from uuid import UUID

    # Convert string to UUID
    try:
        uuid_id = UUID(tag_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid tag ID format") from e

    tag = db.query(Tag).filter(Tag.id == uuid_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if tag.is_predefined:
        raise HTTPException(status_code=400, detail="Cannot delete predefined tags")

    db.delete(tag)  # CASCADE will remove from url_tags and campaign_tags
    db.commit()

    return Response(status_code=204)
