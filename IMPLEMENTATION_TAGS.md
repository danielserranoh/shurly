# Tags Feature Implementation Plan
**Feature:** Global tag system with predefined + user-created tags
**Version:** 1.0
**Target:** Phase 4.1

---

## Table of Contents
1. [Feature Overview](#1-feature-overview)
2. [Database Schema](#2-database-schema)
3. [Configuration](#3-configuration)
4. [API Endpoints](#4-api-endpoints)
5. [Backend Implementation](#5-backend-implementation)
6. [Frontend Components](#6-frontend-components-pending-ux-designs)
7. [User Flows](#7-user-flows)
8. [Testing Strategy](#8-testing-strategy)
9. [Implementation Checklist](#9-implementation-checklist)

---

## 1. Feature Overview

### Core Functionality
- **Global tag library** shared across all users (team-level)
- **Predefined tags** from config file (marketing categories)
- **User-created tags** with full CRUD operations
- **Multiple tags per URL** (no limit)
- **Color-coded categories** for predefined tags
- **Case-insensitive** tag names (stored lowercase)
- **Campaign-level tagging** (applies to all campaign URLs)

### User Stories
```
As a marketer, I want to:
1. Tag URLs with predefined categories (email, social, direct, etc.)
2. Create custom tags for specific campaigns/initiatives
3. Filter my URL list by tags (like Pinterest)
4. Apply tags to entire campaigns
5. See tags on URL cards and details pages
6. Bulk-tag multiple URLs at once
```

---

## 2. Database Schema

### 2.1 Tags Table
```sql
CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(30) NOT NULL UNIQUE,  -- Stored in lowercase
    display_name VARCHAR(30) NOT NULL,  -- Original case for display
    color VARCHAR(20) NOT NULL,         -- Hex color or predefined name
    is_predefined BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,  -- NULL for predefined
    CONSTRAINT name_lowercase CHECK (name = LOWER(name))
);

CREATE INDEX idx_tags_name ON tags(name);
CREATE INDEX idx_tags_is_predefined ON tags(is_predefined);
```

**SQLAlchemy Model:**
```python
# server/core/models/tag.py
from sqlalchemy import Boolean, Column, DateTime, String, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from server.core import Base

class Tag(Base):
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(30), unique=True, nullable=False)  # lowercase
    display_name = Column(String(30), nullable=False)  # original case
    color = Column(String(20), nullable=False)  # e.g., "blue-500", "#3B82F6"
    is_predefined = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    urls = relationship("URL", secondary="url_tags", back_populates="tags")
    campaigns = relationship("Campaign", secondary="campaign_tags", back_populates="tags")

    __table_args__ = (
        CheckConstraint("name = LOWER(name)", name="name_lowercase_check"),
    )

    def __repr__(self):
        return f"<Tag {self.display_name} ({self.name})>"
```

### 2.2 URL-Tags Association Table (Many-to-Many)
```sql
CREATE TABLE url_tags (
    url_id UUID REFERENCES urls(id) ON DELETE CASCADE,
    tag_id UUID REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (url_id, tag_id)
);

CREATE INDEX idx_url_tags_url_id ON url_tags(url_id);
CREATE INDEX idx_url_tags_tag_id ON url_tags(tag_id);
```

**SQLAlchemy Table:**
```python
# server/core/models/url.py (add to URL model)
from sqlalchemy import Table

url_tags = Table(
    "url_tags",
    Base.metadata,
    Column("url_id", UUID(as_uuid=True), ForeignKey("urls.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
)

# Update URL model
class URL(Base):
    # ... existing fields ...

    # Add relationship
    tags = relationship("Tag", secondary="url_tags", back_populates="urls")
```

### 2.3 Campaign-Tags Association Table
```sql
CREATE TABLE campaign_tags (
    campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
    tag_id UUID REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (campaign_id, tag_id)
);

CREATE INDEX idx_campaign_tags_campaign_id ON campaign_tags(campaign_id);
CREATE INDEX idx_campaign_tags_tag_id ON campaign_tags(tag_id);
```

**SQLAlchemy Table:**
```python
# server/core/models/campaign.py (add to Campaign model)
campaign_tags = Table(
    "campaign_tags",
    Base.metadata,
    Column("campaign_id", UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
)

# Update Campaign model
class Campaign(Base):
    # ... existing fields ...

    # Add relationship
    tags = relationship("Tag", secondary="campaign_tags", back_populates="campaigns")
```

---

## 3. Configuration

### 3.1 Predefined Tags Config
**File:** `server/core/config.py`

```python
# Add to Settings class
class Settings(BaseSettings):
    # ... existing settings ...

    # Predefined tags configuration
    PREDEFINED_TAGS: dict = {
        "channels": {
            "color": "blue-500",
            "tags": ["email", "social", "sms", "push", "direct-mail"]
        },
        "intent": {
            "color": "green-500",
            "tags": ["awareness", "consideration", "conversion", "retention"]
        },
        "content-type": {
            "color": "purple-500",
            "tags": ["blog", "landing-page", "product", "promotion", "event"]
        },
        "audience": {
            "color": "orange-500",
            "tags": ["b2b", "b2c", "enterprise", "smb", "consumer"]
        },
        "lifecycle": {
            "color": "pink-500",
            "tags": ["onboarding", "nurture", "upsell", "reactivation", "churn"]
        }
    }

    USER_TAG_COLOR: str = "gray-500"  # Default color for user-created tags

# Example JSON override (optional)
PREDEFINED_TAGS='{
  "channels": {
    "color": "blue-500",
    "tags": ["email", "social", "sms"]
  }
}'
```

### 3.2 Tag Initialization Service
**File:** `server/utils/tags.py`

```python
"""Tag utility functions."""
from sqlalchemy.orm import Session
from server.core.models.tag import Tag
from server.core.config import settings

def initialize_predefined_tags(db: Session) -> None:
    """
    Initialize predefined tags from config.
    Called on app startup or via migration.
    Idempotent - only creates missing tags.
    """
    for category, config in settings.PREDEFINED_TAGS.items():
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
```

---

## 4. API Endpoints

### 4.1 Tag Management Endpoints

#### GET /api/tags
**Purpose:** List all tags (predefined + user-created)

**Query Parameters:**
- `search` (optional): Filter by name (starts-with)
- `is_predefined` (optional): Filter by type (true/false)

**Response:**
```json
{
  "tags": [
    {
      "id": "uuid",
      "name": "email",
      "display_name": "email",
      "color": "blue-500",
      "is_predefined": true,
      "usage_count": 42,
      "created_at": "2025-01-15T10:00:00Z"
    }
  ],
  "total": 15
}
```

**Implementation:**
```python
# server/app/tags.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import Tag, User
from server.core.models.url import url_tags
from server.schemas.tag import TagResponse, TagListResponse

tags_router = APIRouter(prefix="/api/tags", tags=["tags"])

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
```

#### POST /api/tags
**Purpose:** Create a new user tag

**Request:**
```json
{
  "name": "My Campaign"
}
```

**Response:**
```json
{
  "id": "uuid",
  "name": "my campaign",
  "display_name": "My Campaign",
  "color": "gray-500",
  "is_predefined": false,
  "usage_count": 0,
  "created_at": "2025-01-15T10:00:00Z"
}
```

**Validation:**
- Name required, max 30 chars
- Case-insensitive uniqueness check
- No control characters

**Implementation:**
```python
@tags_router.post("", response_model=TagResponse, status_code=201)
def create_tag(
    tag_data: TagCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new user tag."""
    from server.utils.tags import normalize_tag_name, validate_tag_name
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
        color=settings.USER_TAG_COLOR,
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
```

#### PATCH /api/tags/{tag_id}
**Purpose:** Update tag (rename only, user tags only)

**Request:**
```json
{
  "name": "Updated Name"
}
```

**Restrictions:**
- Only user-created tags can be updated
- Cannot update predefined tags
- Name validation applies

**Implementation:**
```python
@tags_router.patch("/{tag_id}", response_model=TagResponse)
def update_tag(
    tag_id: str,
    tag_update: TagUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a user tag (rename only)."""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
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

    return TagResponse.from_orm(tag)
```

#### DELETE /api/tags/{tag_id}
**Purpose:** Delete tag and remove from all URLs

**Restrictions:**
- Only user-created tags can be deleted
- Cascade delete from url_tags and campaign_tags

**Implementation:**
```python
@tags_router.delete("/{tag_id}", status_code=204)
def delete_tag(
    tag_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a user tag (removes from all URLs/campaigns)."""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if tag.is_predefined:
        raise HTTPException(status_code=400, detail="Cannot delete predefined tags")

    db.delete(tag)  # CASCADE will remove from url_tags and campaign_tags
    db.commit()

    return Response(status_code=204)
```

### 4.2 URL Tagging Endpoints

#### PATCH /api/urls/{short_code}/tags
**Purpose:** Update tags for a URL (replace all tags)

**Request:**
```json
{
  "tag_ids": ["uuid1", "uuid2", "uuid3"]
}
```

**Response:**
```json
{
  "short_code": "abc123",
  "tags": [
    {
      "id": "uuid1",
      "name": "email",
      "display_name": "email",
      "color": "blue-500"
    }
  ]
}
```

**Implementation:**
```python
# server/app/urls.py (add to urls_router)
@urls_router.patch("/{short_code}/tags")
def update_url_tags(
    short_code: str,
    tag_data: URLTagUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update tags for a URL."""
    url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.created_by == current_user.id
    ).first()

    if not url:
        raise HTTPException(status_code=404, detail="URL not found")

    # Validate tag IDs exist
    tags = db.query(Tag).filter(Tag.id.in_(tag_data.tag_ids)).all()
    if len(tags) != len(tag_data.tag_ids):
        raise HTTPException(status_code=400, detail="One or more tags not found")

    # Replace tags
    url.tags = tags
    db.commit()
    db.refresh(url)

    return {
        "short_code": url.short_code,
        "tags": [TagResponse.from_orm(tag) for tag in url.tags]
    }
```

#### POST /api/urls/bulk/tags
**Purpose:** Bulk tag multiple URLs

**Request:**
```json
{
  "short_codes": ["abc123", "def456"],
  "tag_ids": ["uuid1", "uuid2"]
}
```

**Response:**
```json
{
  "updated": 2,
  "failed": []
}
```

**Implementation:**
```python
@urls_router.post("/bulk/tags")
def bulk_tag_urls(
    bulk_data: BulkTagUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply tags to multiple URLs."""
    # Fetch URLs
    urls = db.query(URL).filter(
        URL.short_code.in_(bulk_data.short_codes),
        URL.created_by == current_user.id
    ).all()

    # Fetch tags
    tags = db.query(Tag).filter(Tag.id.in_(bulk_data.tag_ids)).all()
    if len(tags) != len(bulk_data.tag_ids):
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
```

### 4.3 Campaign Tagging Endpoints

#### PATCH /api/campaigns/{id}/tags
**Purpose:** Update tags for a campaign (applies to all campaign URLs)

**Request:**
```json
{
  "tag_ids": ["uuid1", "uuid2"]
}
```

**Implementation:**
```python
# server/app/campaigns.py (add to campaigns_router)
@campaigns_router.patch("/{campaign_id}/tags")
def update_campaign_tags(
    campaign_id: str,
    tag_data: CampaignTagUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update tags for a campaign."""
    campaign = db.query(Campaign).filter(
        Campaign.id == campaign_id,
        Campaign.created_by == current_user.id
    ).first()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Validate tags
    tags = db.query(Tag).filter(Tag.id.in_(tag_data.tag_ids)).all()
    if len(tags) != len(tag_data.tag_ids):
        raise HTTPException(status_code=400, detail="One or more tags not found")

    # Update campaign tags
    campaign.tags = tags

    # Apply to all campaign URLs
    campaign_urls = db.query(URL).filter(URL.campaign_id == campaign.id).all()
    for url in campaign_urls:
        url.tags = tags

    db.commit()

    return {
        "campaign_id": campaign.id,
        "tags": [TagResponse.from_orm(tag) for tag in campaign.tags]
    }
```

### 4.4 Filtering Endpoint

#### GET /api/urls?tags=uuid1,uuid2
**Purpose:** Filter URLs by tags

**Query Parameters:**
- `tags`: Comma-separated tag IDs
- `tag_filter`: "all" (AND) or "any" (OR) - default "any"

**Implementation:**
```python
# server/app/urls.py (update existing list_urls endpoint)
@urls_router.get("", response_model=URLListResponse)
def list_urls(
    tags: str | None = Query(None, description="Comma-separated tag IDs"),
    tag_filter: str = Query("any", description="'all' or 'any'"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List user's URLs with optional tag filtering."""
    query = db.query(URL).filter(URL.created_by == current_user.id)

    if tags:
        tag_ids = [t.strip() for t in tags.split(",")]

        if tag_filter == "all":
            # AND logic: URL must have ALL tags
            for tag_id in tag_ids:
                query = query.filter(URL.tags.any(Tag.id == tag_id))
        else:
            # OR logic: URL must have ANY tag
            query = query.filter(URL.tags.any(Tag.id.in_(tag_ids)))

    urls = query.order_by(URL.created_at.desc()).all()

    return URLListResponse(
        urls=[URLResponse.from_orm(url) for url in urls],
        total=len(urls)
    )
```

---

## 5. Backend Implementation

### 5.1 Pydantic Schemas
**File:** `server/schemas/tag.py`

```python
"""Pydantic schemas for tags."""
from pydantic import BaseModel, Field, validator
from datetime import datetime
import uuid as uuid_pkg

class TagBase(BaseModel):
    """Base tag schema."""
    name: str = Field(..., min_length=1, max_length=30)

class TagCreate(TagBase):
    """Schema for creating a tag."""

    @validator("name")
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Tag name cannot be empty")
        if len(v) > 30:
            raise ValueError("Tag name cannot exceed 30 characters")
        return v

class TagUpdate(TagBase):
    """Schema for updating a tag."""
    pass

class TagResponse(BaseModel):
    """Schema for tag response."""
    id: uuid_pkg.UUID
    name: str
    display_name: str
    color: str
    is_predefined: bool
    usage_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True

class TagListResponse(BaseModel):
    """Schema for list of tags."""
    tags: list[TagResponse]
    total: int

class URLTagUpdate(BaseModel):
    """Schema for updating URL tags."""
    tag_ids: list[uuid_pkg.UUID] = Field(..., description="List of tag IDs")

class BulkTagUpdate(BaseModel):
    """Schema for bulk tagging."""
    short_codes: list[str] = Field(..., min_items=1)
    tag_ids: list[uuid_pkg.UUID] = Field(..., min_items=1)

class CampaignTagUpdate(BaseModel):
    """Schema for updating campaign tags."""
    tag_ids: list[uuid_pkg.UUID]
```

### 5.2 Update Existing Schemas
**File:** `server/schemas/url.py`

```python
# Add to URLResponse
class URLResponse(BaseModel):
    # ... existing fields ...
    tags: list[TagResponse] = []  # Add this
```

**File:** `server/schemas/campaign.py`

```python
# Add to CampaignResponse
class CampaignResponse(BaseModel):
    # ... existing fields ...
    tags: list[TagResponse] = []  # Add this
```

### 5.3 App Startup - Initialize Tags
**File:** `main.py`

```python
from fastapi import FastAPI
from server.utils.tags import initialize_predefined_tags
from server.core import get_db

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """Initialize predefined tags on app startup."""
    db = next(get_db())
    try:
        initialize_predefined_tags(db)
    finally:
        db.close()
```

---

## 6. Frontend Components (Pending UX Designs)

### 6.1 Tag Autocomplete Component
**Future File:** `frontend/src/components/TagAutocomplete.astro`

**Features:**
- Search tags (starts-with)
- Display predefined (colored) + user tags (gray)
- "Create new tag" option when no match
- Multi-select with chip display
- Keyboard navigation

**Props:**
```typescript
interface Props {
  selectedTags: Tag[];
  onTagsChange: (tags: Tag[]) => void;
  placeholder?: string;
}
```

### 6.2 Tag Badge Component
**Future File:** `frontend/src/components/TagBadge.astro`

**Features:**
- Color-coded background
- Rounded corners
- Optional remove button (X)

### 6.3 Tag Filter Component
**Future File:** `frontend/src/components/TagFilter.astro`

**Features:**
- Pinterest-style tag filter
- Multi-select
- AND/OR toggle
- Active filter display

### 6.4 Integration Points

#### Create URL Form
```astro
<!-- Add after OG fields -->
<div>
  <label>Tags</label>
  <TagAutocomplete
    selectedTags={selectedTags}
    onTagsChange={handleTagsChange}
  />
</div>
```

#### URL Card
```astro
<!-- Add to URLCard.astro -->
<div class="flex flex-wrap gap-1">
  {url.tags.map(tag => (
    <TagBadge tag={tag} />
  ))}
</div>
```

#### Dashboard Filter
```astro
<!-- Add to dashboard/index.astro -->
<TagFilter
  availableTags={allTags}
  selectedTags={filterTags}
  onFilterChange={handleFilterChange}
/>
```

---

## 7. User Flows

### 7.1 Create URL with Tags
```
User: Create URL form
  ↓
User: Enter URL details
  ↓
User: Click tag autocomplete
  ↓
System: Show predefined + user tags
  ↓
User: Type to search OR select existing
  ↓
User: Click "Create new tag: X" (if no match)
  ↓
System: Create tag via POST /api/tags
  ↓
System: Add tag to URL
  ↓
User: Submit form
  ↓
System: POST /api/urls with tag_ids
  ↓
Success: URL created with tags
```

### 7.2 Filter URLs by Tags
```
User: Dashboard
  ↓
User: Click tag filter button
  ↓
System: Show all tags with usage counts
  ↓
User: Select tag(s)
  ↓
System: GET /api/urls?tags=uuid1,uuid2
  ↓
System: Show filtered URLs
  ↓
User: Toggle AND/OR filter
  ↓
System: GET /api/urls?tags=uuid1,uuid2&tag_filter=all
```

### 7.3 Bulk Tag URLs
```
User: Dashboard URL list
  ↓
User: Multi-select URLs (checkboxes)
  ↓
User: Click "Add Tags" button
  ↓
System: Show tag autocomplete modal
  ↓
User: Select tags
  ↓
User: Click "Apply"
  ↓
System: POST /api/urls/bulk/tags
  ↓
Success: Tags added to selected URLs
```

### 7.4 Tag Campaign
```
User: Create/Edit Campaign
  ↓
User: Select tags in tag autocomplete
  ↓
User: Save campaign
  ↓
System: POST /api/campaigns with tag_ids
  ↓
System: Apply tags to campaign
  ↓
System: Auto-apply tags to all campaign URLs
```

---

## 8. Testing Strategy

### 8.1 Backend Tests
**File:** `tests/test_tags.py`

```python
@pytest.mark.integration
class TestTagCRUD:
    """Test tag CRUD operations."""

    def test_list_tags_includes_predefined(self, client, auth_headers):
        """Predefined tags should be returned."""
        response = client.get("/api/tags", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0
        # Check for at least one predefined tag
        assert any(tag["is_predefined"] for tag in data["tags"])

    def test_create_user_tag(self, client, auth_headers):
        """User can create custom tag."""
        response = client.post(
            "/api/tags",
            json={"name": "My Campaign"},
            headers=auth_headers
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "my campaign"  # lowercase
        assert data["display_name"] == "My Campaign"
        assert data["is_predefined"] is False
        assert data["color"] == "gray-500"

    def test_create_tag_case_insensitive_duplicate(self, client, auth_headers):
        """Creating tag with different case should fail."""
        client.post("/api/tags", json={"name": "Test"}, headers=auth_headers)
        response = client.post(
            "/api/tags",
            json={"name": "test"},  # Same, different case
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_create_tag_too_long(self, client, auth_headers):
        """Tag name exceeding 30 chars should fail."""
        long_name = "a" * 31
        response = client.post(
            "/api/tags",
            json={"name": long_name},
            headers=auth_headers
        )
        assert response.status_code == 400

    def test_update_user_tag(self, client, auth_headers, db_session, test_user):
        """User can rename their tag."""
        # Create tag
        tag = Tag(
            name="oldname",
            display_name="OldName",
            color="gray-500",
            created_by=test_user.id
        )
        db_session.add(tag)
        db_session.commit()

        # Update
        response = client.patch(
            f"/api/tags/{tag.id}",
            json={"name": "NewName"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "newname"
        assert data["display_name"] == "NewName"

    def test_update_predefined_tag_forbidden(self, client, auth_headers, db_session):
        """Cannot update predefined tags."""
        tag = Tag(
            name="email",
            display_name="email",
            color="blue-500",
            is_predefined=True
        )
        db_session.add(tag)
        db_session.commit()

        response = client.patch(
            f"/api/tags/{tag.id}",
            json={"name": "NewName"},
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "predefined" in response.json()["detail"].lower()

    def test_delete_user_tag(self, client, auth_headers, db_session, test_user):
        """User can delete their tag."""
        tag = Tag(
            name="deleteme",
            display_name="DeleteMe",
            color="gray-500",
            created_by=test_user.id
        )
        db_session.add(tag)
        db_session.commit()
        tag_id = tag.id

        response = client.delete(f"/api/tags/{tag_id}", headers=auth_headers)
        assert response.status_code == 204

        # Verify deleted
        assert db_session.query(Tag).filter(Tag.id == tag_id).first() is None

    def test_delete_tag_removes_from_urls(self, client, auth_headers, db_session, test_user):
        """Deleting tag removes it from all URLs."""
        # Create tag
        tag = Tag(name="test", display_name="Test", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create URL with tag
        url = URL(
            short_code="abc123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id
        )
        url.tags.append(tag)
        db_session.add(url)
        db_session.commit()

        # Delete tag
        client.delete(f"/api/tags/{tag.id}", headers=auth_headers)

        # Verify URL has no tags
        db_session.refresh(url)
        assert len(url.tags) == 0

@pytest.mark.integration
class TestURLTagging:
    """Test URL tagging functionality."""

    def test_add_tags_to_url(self, client, auth_headers, db_session, test_user):
        """Can add tags to URL."""
        # Create tags
        tag1 = Tag(name="email", display_name="email", color="blue-500", is_predefined=True)
        tag2 = Tag(name="campaign", display_name="Campaign", color="gray-500", created_by=test_user.id)
        db_session.add_all([tag1, tag2])

        # Create URL
        url = URL(
            short_code="test123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id
        )
        db_session.add(url)
        db_session.commit()

        # Add tags
        response = client.patch(
            f"/api/urls/test123/tags",
            json={"tag_ids": [str(tag1.id), str(tag2.id)]},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["tags"]) == 2

    def test_bulk_tag_urls(self, client, auth_headers, db_session, test_user):
        """Can bulk tag multiple URLs."""
        # Create tag
        tag = Tag(name="bulk", display_name="Bulk", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create URLs
        url1 = URL(short_code="url1", original_url="https://a.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url2 = URL(short_code="url2", original_url="https://b.com", url_type=URLType.STANDARD, created_by=test_user.id)
        db_session.add_all([url1, url2])
        db_session.commit()

        # Bulk tag
        response = client.post(
            "/api/urls/bulk/tags",
            json={
                "short_codes": ["url1", "url2"],
                "tag_ids": [str(tag.id)]
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["updated"] == 2

@pytest.mark.integration
class TestURLFiltering:
    """Test filtering URLs by tags."""

    def test_filter_urls_by_tag(self, client, auth_headers, db_session, test_user):
        """Filter URLs by tag."""
        # Create tag
        tag = Tag(name="filter", display_name="Filter", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create URLs (one with tag, one without)
        url1 = URL(short_code="with", original_url="https://a.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url1.tags.append(tag)
        url2 = URL(short_code="without", original_url="https://b.com", url_type=URLType.STANDARD, created_by=test_user.id)
        db_session.add_all([url1, url2])
        db_session.commit()

        # Filter
        response = client.get(f"/api/urls?tags={tag.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["urls"][0]["short_code"] == "with"
```

### 8.2 Tag Initialization Tests
**File:** `tests/test_tag_initialization.py`

```python
def test_predefined_tags_initialized(db_session):
    """Predefined tags should be created on startup."""
    from server.utils.tags import initialize_predefined_tags

    initialize_predefined_tags(db_session)

    tags = db_session.query(Tag).filter(Tag.is_predefined == True).all()
    assert len(tags) > 0

    # Check for specific tags
    email_tag = db_session.query(Tag).filter(Tag.name == "email").first()
    assert email_tag is not None
    assert email_tag.color == "blue-500"

def test_predefined_tags_idempotent(db_session):
    """Running initialization twice should not create duplicates."""
    from server.utils.tags import initialize_predefined_tags

    initialize_predefined_tags(db_session)
    count1 = db_session.query(Tag).count()

    initialize_predefined_tags(db_session)
    count2 = db_session.query(Tag).count()

    assert count1 == count2
```

---

## 9. Implementation Checklist

### Phase 1: Backend Core (TDD)
- [ ] **Database Schema**
  - [ ] Create Tag model (`server/core/models/tag.py`)
  - [ ] Create url_tags association table
  - [ ] Create campaign_tags association table
  - [ ] Add relationships to URL model
  - [ ] Add relationships to Campaign model
  - [ ] Create migration script

- [ ] **Configuration**
  - [ ] Add PREDEFINED_TAGS to settings
  - [ ] Create tag initialization utility (`server/utils/tags.py`)
  - [ ] Add startup event to main.py

- [ ] **Schemas**
  - [ ] Create `server/schemas/tag.py` (TagCreate, TagUpdate, TagResponse, etc.)
  - [ ] Update URLResponse to include tags
  - [ ] Update CampaignResponse to include tags

- [ ] **API Endpoints - Tags**
  - [ ] GET /api/tags (list with filtering)
  - [ ] POST /api/tags (create user tag)
  - [ ] PATCH /api/tags/{id} (rename user tag)
  - [ ] DELETE /api/tags/{id} (delete user tag)

- [ ] **API Endpoints - URL Tagging**
  - [ ] PATCH /api/urls/{code}/tags (update URL tags)
  - [ ] POST /api/urls/bulk/tags (bulk tag URLs)
  - [ ] Update GET /api/urls to support tag filtering

- [ ] **API Endpoints - Campaign Tagging**
  - [ ] PATCH /api/campaigns/{id}/tags (update campaign tags)
  - [ ] Update POST /api/campaigns to accept tags

- [ ] **Tests** (Write FIRST, TDD)
  - [ ] test_tags.py - CRUD operations (20+ tests)
  - [ ] test_tag_initialization.py - Startup tests
  - [ ] test_url_tagging.py - URL tagging tests
  - [ ] test_tag_filtering.py - Filter tests
  - [ ] Verify all 130+ existing tests still pass

### Phase 2: Frontend (After UX Designs)
- [ ] **Components**
  - [ ] TagBadge component (colored badges)
  - [ ] TagAutocomplete component (search + create)
  - [ ] TagFilter component (Pinterest-style)

- [ ] **Integration**
  - [ ] Add tags to Create URL form
  - [ ] Add tags to URL Card display
  - [ ] Add tags to URL Details page
  - [ ] Add tag filter to Dashboard
  - [ ] Add bulk tagging UI
  - [ ] Add tags to Campaign create/edit

- [ ] **API Integration**
  - [ ] Fetch tags on autocomplete
  - [ ] Create tags inline
  - [ ] Apply tags to URLs
  - [ ] Filter URLs by tags
  - [ ] Update type definitions

### Phase 3: Polish
- [ ] **Documentation**
  - [ ] Update API docs
  - [ ] Update README
  - [ ] Add tag examples to ROADMAP

- [ ] **Performance**
  - [ ] Add database indexes
  - [ ] Optimize tag queries
  - [ ] Cache predefined tags

- [ ] **Testing**
  - [ ] Manual testing all flows
  - [ ] Cross-browser testing
  - [ ] Mobile testing

---

## Appendix A: Example Predefined Tags

### Channels (blue-500)
- email
- social
- sms
- push
- direct-mail
- organic-search
- paid-search
- display-ads
- affiliate

### Intent (green-500)
- awareness
- consideration
- conversion
- retention
- advocacy

### Content Type (purple-500)
- blog
- landing-page
- product
- promotion
- event
- webinar
- whitepaper
- case-study

### Audience (orange-500)
- b2b
- b2c
- enterprise
- smb
- consumer
- partner
- internal

### Lifecycle (pink-500)
- onboarding
- nurture
- upsell
- cross-sell
- reactivation
- churn-prevention
- win-back

---

## Appendix B: Database Migration Script

```python
"""Add tags support

Revision ID: add_tags
Revises: previous_migration
Create Date: 2025-01-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # Create tags table
    op.create_table(
        'tags',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(30), nullable=False),
        sa.Column('display_name', sa.String(30), nullable=False),
        sa.Column('color', sa.String(20), nullable=False),
        sa.Column('is_predefined', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.CheckConstraint("name = LOWER(name)", name='name_lowercase_check')
    )
    op.create_index('idx_tags_name', 'tags', ['name'])
    op.create_index('idx_tags_is_predefined', 'tags', ['is_predefined'])

    # Create url_tags association table
    op.create_table(
        'url_tags',
        sa.Column('url_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tag_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['url_id'], ['urls.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('url_id', 'tag_id')
    )
    op.create_index('idx_url_tags_url_id', 'url_tags', ['url_id'])
    op.create_index('idx_url_tags_tag_id', 'url_tags', ['tag_id'])

    # Create campaign_tags association table
    op.create_table(
        'campaign_tags',
        sa.Column('campaign_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tag_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('campaign_id', 'tag_id')
    )
    op.create_index('idx_campaign_tags_campaign_id', 'campaign_tags', ['campaign_id'])
    op.create_index('idx_campaign_tags_tag_id', 'campaign_tags', ['tag_id'])

def downgrade():
    op.drop_table('campaign_tags')
    op.drop_table('url_tags')
    op.drop_table('tags')
```

---

**End of Implementation Plan**
