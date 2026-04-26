# Implementation Tasks - Rebrandly Insights

**Based on**: REBRANDLY_API_ANALYSIS.md
**Created**: 2025-11-09
**Target**: Enhance Shurly before AWS deployment

---

## Phase 3.6: Critical Pre-Deployment Tasks

**Estimated Time**: 2-3 hours
**Deadline**: Before AWS deployment
**Goal**: Complete basic CRUD and add essential metadata

---

### Task 1: Add Title Field to URLs ⭐ CRITICAL

**Why**: User-friendly descriptions, better dashboard UX
**Effort**: 30 minutes

#### Backend Changes

1. **Database Migration**:
```sql
-- Add title column to urls table
ALTER TABLE urls ADD COLUMN title VARCHAR(255);

-- Optional: Set default titles for existing URLs
UPDATE urls
SET title = SUBSTRING(original_url FROM 'https?://([^/]+)')
WHERE title IS NULL;
```

2. **Update Model** (`server/core/models/url.py`):
```python
class URL(Base):
    # ... existing fields ...
    title = Column(String(255), nullable=True)
```

3. **Update Schemas** (`server/schemas/urls.py`):
```python
class URLCreate(BaseModel):
    original_url: HttpUrl
    custom_code: str | None = None
    title: str | None = None  # Add this
    # ... rest

class URLResponse(BaseModel):
    id: int
    short_code: str
    original_url: str
    title: str | None  # Add this
    # ... rest
```

4. **Update Endpoints** (`server/app/urls.py`):
```python
@router.post("", response_model=URLResponse)
async def create_url(url_data: URLCreate, ...):
    # ... existing logic ...
    new_url = URL(
        # ... existing fields ...
        title=url_data.title,  # Add this
    )
```

#### Frontend Changes

5. **Add Title Input** (`frontend/src/pages/dashboard/index.astro`):
```html
<!-- In the create URL form -->
<label class="block mb-2 text-sm font-medium">
  Title (optional)
  <input
    type="text"
    name="title"
    placeholder="Q4 Email Campaign"
    maxlength="255"
    class="w-full px-3 py-2 border rounded-lg"
  />
</label>
```

6. **Display Title** (`frontend/src/components/URLCard.astro`):
```html
<!-- Show title instead of/above URL -->
<h3 class="text-lg font-semibold">
  {url.title || url.original_url}
</h3>
{url.title && (
  <p class="text-sm text-gray-500 truncate">{url.original_url}</p>
)}
```

#### Tests

7. **Add Test** (`tests/test_urls.py`):
```python
def test_create_url_with_title(client, auth_headers):
    response = client.post(
        "/api/urls",
        json={
            "original_url": "https://example.com",
            "title": "Test Campaign"
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Campaign"
```

**Acceptance Criteria**:
- ✅ URLs can be created with optional title
- ✅ Title appears in API responses
- ✅ Title displayed in dashboard
- ✅ Test passes

---

### Task 2: Add Last Click Timestamp ⭐ CRITICAL

**Why**: Better analytics, identify stale links
**Effort**: 20 minutes

#### Backend Changes

1. **Database Migration**:
```sql
ALTER TABLE urls ADD COLUMN last_click_at TIMESTAMP;

-- Optionally set to latest visitor timestamp for existing URLs
UPDATE urls u
SET last_click_at = (
    SELECT MAX(clicked_at)
    FROM visitors v
    WHERE v.short_code = u.short_code
);
```

2. **Update Model** (`server/core/models/url.py`):
```python
from datetime import datetime

class URL(Base):
    # ... existing fields ...
    last_click_at = Column(DateTime(timezone=True), nullable=True)
```

3. **Update Redirect Endpoint** (`main.py`):
```python
@app.get("/{short_code}")
async def redirect_url(short_code: str, ...):
    # ... existing lookup logic ...

    # Update last click timestamp
    url.last_click_at = datetime.now(timezone.utc)

    # ... rest of redirect logic ...
```

4. **Update Schema** (`server/schemas/urls.py`):
```python
class URLResponse(BaseModel):
    # ... existing fields ...
    last_click_at: datetime | None
```

#### Frontend Changes

5. **Display Last Click** (`frontend/src/pages/dashboard/urls/[code].astro`):
```html
<div class="stat-card">
  <h4>Last Clicked</h4>
  <p>
    {url.last_click_at
      ? new Date(url.last_click_at).toLocaleString()
      : 'Never'
    }
  </p>
</div>
```

#### Tests

6. **Add Test** (`tests/test_urls.py`):
```python
def test_redirect_updates_last_click_at(client, sample_url):
    # First redirect
    response = client.get(f"/{sample_url.short_code}")
    assert response.status_code == 302

    # Get URL and check last_click_at is set
    response = client.get(f"/api/urls/{sample_url.short_code}")
    data = response.json()
    assert data["last_click_at"] is not None
```

**Acceptance Criteria**:
- ✅ last_click_at updated on every redirect
- ✅ Timestamp visible in API response
- ✅ Displayed in URL details page
- ✅ Test passes

---

### Task 3: Add Update/Edit Link Endpoint ⭐ CRITICAL

**Why**: Basic CRUD operation, user expectation
**Effort**: 45 minutes

#### Backend Changes

1. **Add Update Schema** (`server/schemas/urls.py`):
```python
class URLUpdate(BaseModel):
    title: str | None = None
    original_url: HttpUrl | None = None
    forward_parameters: bool | None = None

    class Config:
        extra = "forbid"  # Prevent updating immutable fields
```

2. **Add PATCH Endpoint** (`server/app/urls.py`):
```python
@router.patch("/{short_code}", response_model=URLResponse)
async def update_url(
    short_code: str,
    url_update: URLUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Get URL
    url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.created_by == current_user.id
    ).first()

    if not url:
        raise HTTPException(status_code=404, detail="URL not found")

    # Update fields (only non-None values)
    update_data = url_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(url, field, value)

    db.commit()
    db.refresh(url)

    return url
```

#### Frontend Changes

3. **Add Edit Button** (`frontend/src/pages/dashboard/urls/[code].astro`):
```html
<button id="editBtn" class="btn btn-secondary">
  Edit URL
</button>

<dialog id="editModal">
  <form id="editForm">
    <label>
      Title
      <input name="title" value={url.title} />
    </label>
    <label>
      Destination URL
      <input name="original_url" value={url.original_url} />
    </label>
    <button type="submit">Save</button>
  </form>
</dialog>

<script>
  const editBtn = document.getElementById('editBtn');
  const editModal = document.getElementById('editModal');
  const editForm = document.getElementById('editForm');

  editBtn?.addEventListener('click', () => editModal?.showModal());

  editForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    const data = Object.fromEntries(formData);

    await fetch(`/api/urls/${url.short_code}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      },
      body: JSON.stringify(data)
    });

    window.location.reload();
  });
</script>
```

#### Tests

4. **Add Tests** (`tests/test_urls.py`):
```python
def test_update_url_title(client, auth_headers, sample_url):
    response = client.patch(
        f"/api/urls/{sample_url.short_code}",
        json={"title": "Updated Title"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["original_url"] == sample_url.original_url  # Unchanged

def test_update_url_destination(client, auth_headers, sample_url):
    response = client.patch(
        f"/api/urls/{sample_url.short_code}",
        json={"original_url": "https://new-destination.com"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["original_url"] == "https://new-destination.com"

def test_update_url_unauthorized(client, sample_url):
    response = client.patch(
        f"/api/urls/{sample_url.short_code}",
        json={"title": "Hacked"},
    )
    assert response.status_code == 401

def test_update_url_not_owner(client, auth_headers_other_user, sample_url):
    response = client.patch(
        f"/api/urls/{sample_url.short_code}",
        json={"title": "Not mine"},
        headers=auth_headers_other_user,
    )
    assert response.status_code == 404  # Or 403
```

**Acceptance Criteria**:
- ✅ PATCH endpoint allows updating title, original_url
- ✅ Cannot update short_code, created_by (immutable)
- ✅ Only URL owner can update
- ✅ Frontend has edit UI
- ✅ Tests pass

---

### Task 4: Add Forward Parameters Flag 🟡 MEDIUM

**Why**: User control over query param behavior
**Effort**: 30 minutes

#### Backend Changes

1. **Database Migration**:
```sql
ALTER TABLE urls ADD COLUMN forward_parameters BOOLEAN DEFAULT true;
```

2. **Update Model** (`server/core/models/url.py`):
```python
class URL(Base):
    # ... existing fields ...
    forward_parameters = Column(Boolean, default=True, nullable=False)
```

3. **Update Redirect Logic** (`main.py`):
```python
@app.get("/{short_code}")
async def redirect_url(short_code: str, request: Request, ...):
    # ... lookup url ...

    # Build redirect URL
    redirect_url = url.original_url

    # Only forward params if flag is true
    if url.forward_parameters:
        query_params = dict(request.query_params)
        if url.url_type == "campaign" and url.user_data:
            query_params.update(url.user_data)

        if query_params:
            redirect_url += "?" + urlencode(query_params)
    elif url.url_type == "campaign" and url.user_data:
        # Always add campaign params, even if flag is false
        redirect_url += "?" + urlencode(url.user_data)

    return RedirectResponse(url=redirect_url, status_code=302)
```

4. **Update Schemas**:
```python
class URLCreate(BaseModel):
    # ... existing ...
    forward_parameters: bool = True

class URLResponse(BaseModel):
    # ... existing ...
    forward_parameters: bool
```

#### Frontend Changes

5. **Add Checkbox** (`frontend/src/pages/dashboard/index.astro`):
```html
<label class="flex items-center">
  <input
    type="checkbox"
    name="forward_parameters"
    checked
    class="mr-2"
  />
  Forward query parameters (e.g., ?utm_source=email)
</label>
```

#### Tests

6. **Add Test** (`tests/test_urls.py`):
```python
def test_redirect_with_forward_params_false(client, db):
    # Create URL with forward_parameters=False
    url = URL(
        original_url="https://example.com",
        short_code="test123",
        url_type="standard",
        forward_parameters=False,
        created_by=1,
    )
    db.add(url)
    db.commit()

    # Try to redirect with query params
    response = client.get("/test123?utm_source=email", follow_redirects=False)
    assert response.status_code == 302

    # Params should NOT be forwarded
    location = response.headers["location"]
    assert "utm_source" not in location
    assert location == "https://example.com"
```

**Acceptance Criteria**:
- ✅ forward_parameters field in model
- ✅ Redirect logic respects flag
- ✅ Campaign params always added (regardless of flag)
- ✅ UI has checkbox
- ✅ Test passes

---

## Phase 4: Post-Deployment Enhancements

**Estimated Time**: 1-2 days
**Timeline**: After AWS deployment and initial testing

---

### Task 5: Implement Tags System ⭐⭐⭐ HIGH VALUE

**Why**: Flexible organization, cross-campaign analytics
**Effort**: 4-6 hours

#### Backend Changes

1. **New Models** (`server/core/models/tag.py`):
```python
from sqlalchemy import Column, Integer, String, ForeignKey, Table, DateTime
from sqlalchemy.orm import relationship
from server.core import Base

# Association table
url_tags = Table(
    'url_tags',
    Base.metadata,
    Column('url_id', Integer, ForeignKey('urls.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True),
)

class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    creator = relationship("User", back_populates="tags")
    urls = relationship("URL", secondary=url_tags, back_populates="tags")

    __table_args__ = (
        # Unique constraint: user can't have duplicate tag names
        UniqueConstraint('name', 'created_by', name='unique_tag_per_user'),
    )
```

2. **Update URL Model**:
```python
class URL(Base):
    # ... existing fields ...
    tags = relationship("Tag", secondary=url_tags, back_populates="urls")
```

3. **Tag Schemas** (`server/schemas/tags.py`):
```python
class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9:_-]+$')

class TagResponse(BaseModel):
    id: int
    name: str
    created_at: datetime

    class Config:
        from_attributes = True

class TagWithCount(TagResponse):
    url_count: int
```

4. **Tag Endpoints** (`server/app/tags.py`):
```python
from fastapi import APIRouter, Depends, HTTPException
from server.schemas.tags import TagCreate, TagResponse, TagWithCount

router = APIRouter(prefix="/api/tags", tags=["tags"])

@router.post("", response_model=TagResponse, status_code=201)
async def create_tag(
    tag_data: TagCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Check if tag already exists
    existing = db.query(Tag).filter(
        Tag.name == tag_data.name,
        Tag.created_by == current_user.id
    ).first()

    if existing:
        return existing  # Idempotent

    tag = Tag(name=tag_data.name, created_by=current_user.id)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag

@router.get("", response_model=list[TagWithCount])
async def list_tags(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tags = db.query(
        Tag.id,
        Tag.name,
        Tag.created_at,
        func.count(url_tags.c.url_id).label("url_count")
    ).outerjoin(url_tags).filter(
        Tag.created_by == current_user.id
    ).group_by(Tag.id).all()

    return [
        {"id": t.id, "name": t.name, "created_at": t.created_at, "url_count": t.url_count}
        for t in tags
    ]

@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tag = db.query(Tag).filter(
        Tag.id == tag_id,
        Tag.created_by == current_user.id
    ).first()

    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    db.delete(tag)
    db.commit()
```

5. **Update URL Endpoints**:
```python
# In URLCreate schema
class URLCreate(BaseModel):
    # ... existing ...
    tags: list[str] = []  # Tag names

# In create_url endpoint
@router.post("", response_model=URLResponse)
async def create_url(url_data: URLCreate, ...):
    # ... create URL ...

    # Add tags
    if url_data.tags:
        for tag_name in url_data.tags:
            # Get or create tag
            tag = db.query(Tag).filter(
                Tag.name == tag_name,
                Tag.created_by == current_user.id
            ).first()

            if not tag:
                tag = Tag(name=tag_name, created_by=current_user.id)
                db.add(tag)

            new_url.tags.append(tag)

    db.commit()
    # ...
```

#### Frontend Changes

6. **Tag Input Component** (multi-select or tag input):
```html
<!-- In create URL form -->
<label class="block mb-2">
  Tags (optional)
  <div id="tagInput" class="border rounded-lg p-2">
    <div id="selectedTags" class="flex flex-wrap gap-2 mb-2"></div>
    <input
      type="text"
      id="tagSearch"
      placeholder="Type to add tags (e.g., email, campaign)"
      class="w-full border-0 focus:outline-none"
    />
  </div>
  <input type="hidden" name="tags" id="tagsHidden" />
</label>

<script>
  // Tag input logic
  const selectedTags = new Set();
  const tagInput = document.getElementById('tagSearch');
  const tagsContainer = document.getElementById('selectedTags');
  const tagsHidden = document.getElementById('tagsHidden');

  tagInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      const tag = tagInput.value.trim();
      if (tag && !selectedTags.has(tag)) {
        selectedTags.add(tag);
        renderTags();
        tagInput.value = '';
      }
    }
  });

  function renderTags() {
    tagsContainer.innerHTML = Array.from(selectedTags)
      .map(tag => `
        <span class="tag bg-blue-100 text-blue-800 px-2 py-1 rounded">
          ${tag}
          <button type="button" onclick="removeTag('${tag}')" class="ml-1">×</button>
        </span>
      `).join('');

    tagsHidden.value = Array.from(selectedTags).join(',');
  }

  window.removeTag = (tag) => {
    selectedTags.delete(tag);
    renderTags();
  };
</script>
```

7. **Tags Page** (`frontend/src/pages/dashboard/tags.astro`):
```html
---
// List all tags with URL counts
const tags = await apiGet('/api/tags');
---

<Layout title="Tags">
  <h1>Tags</h1>

  <div class="grid gap-4">
    {tags.map(tag => (
      <div class="card">
        <h3>{tag.name}</h3>
        <p>{tag.url_count} URLs</p>
        <a href={`/dashboard/tags/${tag.id}`}>View URLs</a>
      </div>
    ))}
  </div>
</Layout>
```

#### Tests

8. **Add Tests** (`tests/test_tags.py`):
```python
def test_create_tag(client, auth_headers):
    response = client.post(
        "/api/tags",
        json={"name": "marketing"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["name"] == "marketing"

def test_create_url_with_tags(client, auth_headers):
    response = client.post(
        "/api/urls",
        json={
            "original_url": "https://example.com",
            "tags": ["email", "campaign:summer"]
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["tags"]) == 2
    assert any(t["name"] == "email" for t in data["tags"])

def test_list_tags_with_counts(client, auth_headers, sample_url_with_tags):
    response = client.get("/api/tags", headers=auth_headers)
    assert response.status_code == 200
    tags = response.json()
    assert any(t["url_count"] > 0 for t in tags)
```

**Acceptance Criteria**:
- ✅ Tag CRUD endpoints
- ✅ URL creation with tags
- ✅ Tag filtering on URL list
- ✅ Tag analytics page
- ✅ Tests pass

---

### Task 6: Add Sorting and Filtering 🟡 MEDIUM

**Why**: Better user experience, efficient navigation
**Effort**: 2 hours

#### Backend Changes

1. **Update List Endpoint** (`server/app/urls.py`):
```python
from enum import Enum

class OrderByField(str, Enum):
    created_at = "created_at"
    clicks = "clicks"
    last_click_at = "last_click_at"
    title = "title"

class OrderDirection(str, Enum):
    asc = "asc"
    desc = "desc"

@router.get("", response_model=list[URLResponse])
async def list_urls(
    skip: int = 0,
    limit: int = 25,  # Reduced from 100
    order_by: OrderByField = OrderByField.created_at,
    order_dir: OrderDirection = OrderDirection.desc,
    url_type: str | None = None,
    campaign_id: int | None = None,
    tag_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(URL).filter(URL.created_by == current_user.id)

    # Apply filters
    if url_type:
        query = query.filter(URL.url_type == url_type)
    if campaign_id:
        query = query.filter(URL.campaign_id == campaign_id)
    if tag_id:
        query = query.join(URL.tags).filter(Tag.id == tag_id)

    # Apply ordering
    order_column = getattr(URL, order_by.value)
    if order_dir == OrderDirection.desc:
        order_column = order_column.desc()
    query = query.order_by(order_column)

    urls = query.offset(skip).limit(limit).all()
    return urls
```

#### Frontend Changes

2. **Add Sort/Filter UI** (`frontend/src/pages/dashboard/index.astro`):
```html
<div class="filters mb-4">
  <select id="sortBy" class="select">
    <option value="created_at:desc">Newest First</option>
    <option value="created_at:asc">Oldest First</option>
    <option value="clicks:desc">Most Clicks</option>
    <option value="last_click_at:desc">Recently Clicked</option>
  </select>

  <select id="filterType" class="select">
    <option value="">All Types</option>
    <option value="standard">Standard</option>
    <option value="custom">Custom</option>
    <option value="campaign">Campaign</option>
  </select>

  <select id="filterTag" class="select">
    <option value="">All Tags</option>
    <!-- Populated from /api/tags -->
  </select>
</div>

<script>
  // Re-fetch URLs when filters change
  document.getElementById('sortBy')?.addEventListener('change', (e) => {
    const [field, dir] = e.target.value.split(':');
    fetchURLs({ order_by: field, order_dir: dir });
  });

  document.getElementById('filterType')?.addEventListener('change', (e) => {
    fetchURLs({ url_type: e.target.value });
  });

  async function fetchURLs(params = {}) {
    const query = new URLSearchParams(params).toString();
    const urls = await apiGet(`/api/urls?${query}`);
    renderURLs(urls);
  }
</script>
```

**Acceptance Criteria**:
- ✅ Sort by created_at, clicks, last_click_at, title
- ✅ Filter by url_type, campaign_id, tag_id
- ✅ Frontend dropdowns for sorting/filtering
- ✅ Query params in URL (shareable links)

---

### Task 7: Implement Rate Limiting 🟡 MEDIUM

**Why**: Security, prevent abuse
**Effort**: 1 hour (mostly AWS config)

#### AWS Configuration

1. **Update SAM Template** (`template.yaml`):
```yaml
Resources:
  ShurlApiGateway:
    Type: AWS::Serverless::HttpApi
    Properties:
      # ... existing ...
      DefaultRouteSettings:
        ThrottlingBurstLimit: 100  # Max concurrent requests
        ThrottlingRateLimit: 50    # Requests per second

  # Optional: Usage plan for API key rate limiting
  ShurlUsagePlan:
    Type: AWS::ApiGateway::UsagePlan
    Properties:
      UsagePlanName: shurl-usage-plan
      Throttle:
        BurstLimit: 200
        RateLimit: 100
      Quota:
        Limit: 50000
        Period: DAY
```

#### Backend Response

2. **Add 429 Handler** (`main.py`):
```python
from fastapi.responses import JSONResponse

@app.exception_handler(429)
async def rate_limit_handler(request: Request, exc):
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please try again later.",
            "retry_after": 60  # seconds
        },
        headers={"Retry-After": "60"}
    )
```

**Acceptance Criteria**:
- ✅ API Gateway throttling configured
- ✅ 429 responses with Retry-After header
- ✅ Documented in README

---

## Testing Checklist

After implementing all tasks, verify:

- [ ] All 104+ existing tests still pass
- [ ] New tests for title field (2 tests)
- [ ] New tests for last_click_at (2 tests)
- [ ] New tests for update endpoint (4 tests)
- [ ] New tests for forward_parameters (2 tests)
- [ ] New tests for tags (6+ tests)
- [ ] Frontend creates URLs with new fields
- [ ] Frontend displays new fields
- [ ] Edit UI works correctly
- [ ] Tag system works end-to-end
- [ ] Sorting and filtering work
- [ ] Rate limiting prevents abuse

**Target**: 120+ tests passing

---

## Documentation Updates

After implementation:

1. Update README.md:
   - Add new features to feature list
   - Update API endpoints section
   - Add rate limiting info

2. Update ROADMAP.md:
   - Mark Phase 3.6 as complete
   - Update feature status

3. Update API documentation:
   - OpenAPI spec (auto-generated by FastAPI)
   - Add examples for new endpoints

---

## Success Metrics

**Phase 3.6 Complete When**:
- ✅ All 4 critical tasks implemented
- ✅ All tests passing (120+)
- ✅ Frontend UI updated
- ✅ Documentation updated
- ✅ Ready for AWS deployment

**Phase 4 Complete When**:
- ✅ Tags system fully functional
- ✅ Sorting and filtering work
- ✅ Rate limiting in place
- ✅ User feedback incorporated

---

## Phase 3.7: Social Media Link Preview (Open Graph) 🔴 CRITICAL

**Why This is Critical**: 70-80% lower CTR on social media without rich previews. Most shortened links are shared on social media - this is table stakes.

**Estimated Time**: 8-10 days
**Priority**: CRITICAL #1 for social media marketing
**Reference**:
- FUNCTIONAL_GAP_ANALYSIS.md Gap #1
- design/Rebrandly-Dashboard.png (shows preview card UI)
- design/Rebrandly-newlink.png (shows preview during creation)

---

### Task 1: Database Schema for Open Graph Metadata

**Effort**: 1 hour

#### Migration Script

Create `migrations/add_opengraph_fields.sql`:

```sql
-- Add Open Graph metadata fields to urls table
ALTER TABLE urls ADD COLUMN og_title VARCHAR(255);
ALTER TABLE urls ADD COLUMN og_description TEXT;
ALTER TABLE urls ADD COLUMN og_image_url TEXT;
ALTER TABLE urls ADD COLUMN og_fetched_at TIMESTAMP;

-- Add index for fetched_at to find stale metadata
CREATE INDEX idx_urls_og_fetched_at ON urls(og_fetched_at)
WHERE og_fetched_at IS NOT NULL;

-- Add comment for documentation
COMMENT ON COLUMN urls.og_title IS 'Open Graph title for social media previews';
COMMENT ON COLUMN urls.og_description IS 'Open Graph description for social media';
COMMENT ON COLUMN urls.og_image_url IS 'Open Graph image URL for social media cards';
COMMENT ON COLUMN urls.og_fetched_at IS 'When metadata was last fetched from destination';
```

#### Model Update

Update `server/core/models/url.py`:

```python
from datetime import datetime

class URL(Base):
    __tablename__ = "urls"

    # ... existing fields ...
    title = Column(String(255), nullable=True)

    # Open Graph metadata for social media previews
    og_title = Column(String(255), nullable=True)
    og_description = Column(Text, nullable=True)
    og_image_url = Column(Text, nullable=True)
    og_fetched_at = Column(DateTime, nullable=True)

    # ... rest of model ...
```

---

### Task 2: Open Graph Metadata Fetcher Utility

**Effort**: 4-5 hours (includes error handling and testing)

#### Install Dependencies

Add to `requirements.txt`:
```
beautifulsoup4==4.12.3
httpx==0.27.0
```

#### Create Fetcher Utility

Create `server/utils/opengraph.py`:

```python
"""Open Graph metadata fetching utilities."""

import httpx
from bs4 import BeautifulSoup
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class OpenGraphMetadata:
    """Open Graph metadata container."""

    def __init__(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        image_url: Optional[str] = None,
        url: Optional[str] = None,
    ):
        self.title = title
        self.description = description
        self.image_url = image_url
        self.url = url

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "og_title": self.title,
            "og_description": self.description,
            "og_image_url": self.image_url,
            "og_url": self.url,
        }

    def has_metadata(self) -> bool:
        """Check if any metadata was found."""
        return any([self.title, self.description, self.image_url])


async def fetch_opengraph_metadata(url: str, timeout: int = 5) -> OpenGraphMetadata:
    """
    Fetch Open Graph metadata from a URL.

    Args:
        url: Destination URL to fetch metadata from
        timeout: Request timeout in seconds (default: 5)

    Returns:
        OpenGraphMetadata object with parsed data

    Example:
        >>> metadata = await fetch_opengraph_metadata("https://example.com")
        >>> print(metadata.title)  # "Example Domain"
    """
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={
                "User-Agent": "Shurly/1.0 (+https://shurl.griddo.io; Link Preview Bot)"
            })

            # Only parse successful responses
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url}: HTTP {response.status_code}")
                return OpenGraphMetadata()

            # Only parse HTML content
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                logger.info(f"Skipping non-HTML content: {content_type}")
                return OpenGraphMetadata()

            # Parse HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # Extract Open Graph tags
            og_title = _extract_og_tag(soup, "og:title")
            og_description = _extract_og_tag(soup, "og:description")
            og_image = _extract_og_tag(soup, "og:image")
            og_url = _extract_og_tag(soup, "og:url")

            # Fallback to standard meta tags if OG tags missing
            if not og_title:
                og_title = _extract_meta_tag(soup, "title") or _extract_title_tag(soup)

            if not og_description:
                og_description = _extract_meta_tag(soup, "description")

            return OpenGraphMetadata(
                title=og_title,
                description=og_description,
                image_url=og_image,
                url=og_url or url,
            )

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching metadata from {url}")
        return OpenGraphMetadata()

    except Exception as e:
        logger.error(f"Error fetching metadata from {url}: {str(e)}")
        return OpenGraphMetadata()


def _extract_og_tag(soup: BeautifulSoup, property_name: str) -> Optional[str]:
    """Extract Open Graph meta tag content."""
    tag = soup.find("meta", property=property_name)
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _extract_meta_tag(soup: BeautifulSoup, name: str) -> Optional[str]:
    """Extract standard meta tag content."""
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _extract_title_tag(soup: BeautifulSoup) -> Optional[str]:
    """Extract <title> tag content as fallback."""
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()
    return None


def is_social_media_crawler(user_agent: str) -> bool:
    """
    Detect if User-Agent is a social media crawler.

    Social media crawlers need to see the preview page with OG tags,
    while regular browsers should get direct redirects.

    Args:
        user_agent: User-Agent header string

    Returns:
        True if social media crawler, False otherwise
    """
    if not user_agent:
        return False

    ua_lower = user_agent.lower()

    # Social media crawler identifiers
    crawlers = [
        "twitterbot",           # Twitter/X
        "facebookexternalhit",  # Facebook
        "linkedinbot",          # LinkedIn
        "whatsapp",             # WhatsApp
        "slackbot",             # Slack
        "discordbot",           # Discord
        "telegrambot",          # Telegram
        "skypeuripreview",      # Skype
        "pinterest",            # Pinterest
        "redditbot",            # Reddit
        "slurp",                # Yahoo (sometimes used by messaging apps)
    ]

    return any(crawler in ua_lower for crawler in crawlers)
```

#### Tests for Fetcher

Add to `tests/test_opengraph.py` (new file):

```python
"""Tests for Open Graph metadata fetching."""

import pytest
from server.utils.opengraph import (
    fetch_opengraph_metadata,
    is_social_media_crawler,
    OpenGraphMetadata,
)


class TestOpenGraphMetadata:
    """Test OpenGraphMetadata class."""

    def test_to_dict(self):
        metadata = OpenGraphMetadata(
            title="Test Title",
            description="Test Description",
            image_url="https://example.com/image.jpg",
        )

        result = metadata.to_dict()
        assert result["og_title"] == "Test Title"
        assert result["og_description"] == "Test Description"
        assert result["og_image_url"] == "https://example.com/image.jpg"

    def test_has_metadata_true(self):
        metadata = OpenGraphMetadata(title="Test")
        assert metadata.has_metadata() is True

    def test_has_metadata_false(self):
        metadata = OpenGraphMetadata()
        assert metadata.has_metadata() is False


class TestSocialMediaCrawlerDetection:
    """Test social media crawler detection."""

    @pytest.mark.parametrize("user_agent,expected", [
        ("Mozilla/5.0 (compatible; Twitterbot/1.0)", True),
        ("facebookexternalhit/1.1", True),
        ("LinkedInBot/1.0", True),
        ("WhatsApp/2.0", True),
        ("Slackbot-LinkExpanding 1.0", True),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", False),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 14_0)", False),
        ("curl/7.68.0", False),
        ("", False),
    ])
    def test_crawler_detection(self, user_agent, expected):
        assert is_social_media_crawler(user_agent) == expected


@pytest.mark.asyncio
class TestFetchOpenGraphMetadata:
    """Test metadata fetching (requires mocking)."""

    async def test_fetch_timeout(self, monkeypatch):
        """Test timeout handling."""
        # Mock httpx to raise timeout
        import httpx

        async def mock_get(*args, **kwargs):
            raise httpx.TimeoutException("Timeout")

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        metadata = await fetch_opengraph_metadata("https://slow-site.com")
        assert not metadata.has_metadata()

    # Add more integration tests with mocked responses
```

---

### Task 3: Preview Page Endpoint

**Effort**: 3-4 hours

#### Create Preview Template

Create `server/templates/preview.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <!-- Open Graph Tags -->
    <meta property="og:title" content="{{ og_title }}" />
    <meta property="og:description" content="{{ og_description }}" />
    {% if og_image_url %}
    <meta property="og:image" content="{{ og_image_url }}" />
    {% endif %}
    <meta property="og:url" content="{{ short_url }}" />
    <meta property="og:type" content="website" />

    <!-- Twitter Card Tags -->
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{{ og_title }}" />
    <meta name="twitter:description" content="{{ og_description }}" />
    {% if og_image_url %}
    <meta name="twitter:image" content="{{ og_image_url }}" />
    {% endif %}

    <!-- Standard Meta Tags -->
    <title>{{ og_title }}</title>
    <meta name="description" content="{{ og_description }}" />

    <!-- Auto-redirect after 2 seconds -->
    <meta http-equiv="refresh" content="2;url={{ destination_url }}" />

    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .container {
            background: white;
            border-radius: 12px;
            padding: 2rem;
            max-width: 500px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
        }
        .logo {
            font-size: 2rem;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 1rem;
        }
        h1 {
            font-size: 1.5rem;
            color: #333;
            margin-bottom: 0.5rem;
        }
        p {
            color: #666;
            margin-bottom: 1.5rem;
        }
        .btn {
            display: inline-block;
            background: #667eea;
            color: white;
            padding: 0.75rem 2rem;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 500;
        }
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(102, 126, 234, 0.3);
            border-radius: 50%;
            border-top-color: #667eea;
            animation: spin 1s linear infinite;
            margin-left: 10px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">shurl</div>
        <h1>{{ og_title }}</h1>
        <p>{{ og_description }}</p>
        <a href="{{ destination_url }}" class="btn">
            Continue to destination
            <span class="spinner"></span>
        </a>
        <p style="font-size: 0.875rem; color: #999; margin-top: 1rem;">
            Redirecting automatically in 2 seconds...
        </p>
    </div>
</body>
</html>
```

#### Update Main Router

Update `main.py` to add template support:

```python
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

app = FastAPI(title="Shurly API")

# Add templates
templates = Jinja2Templates(directory="server/templates")

# ... existing routes ...
```

#### Add Preview Endpoint

Update `main.py` redirect handler:

```python
from server.utils.opengraph import is_social_media_crawler

@app.get("/{short_code}", include_in_schema=False)
async def redirect_short_url(
    short_code: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Redirect short URL to destination.

    - Social media crawlers: Show preview page with Open Graph tags
    - Regular browsers: Direct redirect (302)
    """
    url = db.query(URL).filter(URL.short_code == short_code).first()

    if not url:
        raise HTTPException(status_code=404, detail="Short URL not found")

    # Check User-Agent for social media crawlers
    user_agent = request.headers.get("user-agent", "")

    if is_social_media_crawler(user_agent):
        # Serve preview page with Open Graph tags
        return templates.TemplateResponse(
            "preview.html",
            {
                "request": request,
                "og_title": url.og_title or url.title or url.original_url,
                "og_description": url.og_description or f"Visit {url.original_url}",
                "og_image_url": url.og_image_url,
                "short_url": f"{request.base_url}{short_code}",
                "destination_url": url.original_url,
            },
            headers={"Cache-Control": "public, max-age=300"},  # Cache for 5 min
        )

    # Regular redirect for browsers
    # ... existing redirect logic with visitor tracking ...
```

---

### Task 4: API Endpoints for Preview Management

**Effort**: 2-3 hours

#### Update Schemas

Update `server/schemas/urls.py`:

```python
class URLCreate(BaseModel):
    original_url: HttpUrl
    custom_code: str | None = None
    title: str | None = None

    # Open Graph fields (optional)
    og_title: str | None = Field(None, max_length=255)
    og_description: str | None = None
    og_image_url: HttpUrl | None = None


class URLUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    original_url: HttpUrl | None = None
    forward_parameters: bool | None = None

    # Open Graph fields
    og_title: str | None = Field(None, max_length=255)
    og_description: str | None = None
    og_image_url: HttpUrl | None = None


class URLResponse(BaseModel):
    id: int
    short_code: str
    original_url: str
    title: str | None

    # Open Graph fields
    og_title: str | None
    og_description: str | None
    og_image_url: str | None
    og_fetched_at: datetime | None

    # ... rest


class OpenGraphMetadataResponse(BaseModel):
    """Response for preview endpoint."""
    og_title: str | None
    og_description: str | None
    og_image_url: str | None
    og_url: str
    has_custom_preview: bool
    fetched_at: datetime | None
```

#### Add Preview Endpoints

Add to `server/app/urls.py`:

```python
from server.utils.opengraph import fetch_opengraph_metadata
from datetime import datetime

@router.get("/{short_code}/preview", response_model=OpenGraphMetadataResponse)
async def get_url_preview(
    short_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get Open Graph preview metadata for a URL."""
    url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.created_by == current_user.id,
    ).first()

    if not url:
        raise HTTPException(status_code=404, detail="URL not found")

    has_custom = bool(url.og_title or url.og_description or url.og_image_url)

    return {
        "og_title": url.og_title or url.title,
        "og_description": url.og_description,
        "og_image_url": url.og_image_url,
        "og_url": f"https://shurl.griddo.io/{short_code}",  # TODO: Get from config
        "has_custom_preview": has_custom,
        "fetched_at": url.og_fetched_at,
    }


@router.post("/{short_code}/refresh-preview", response_model=OpenGraphMetadataResponse)
async def refresh_url_preview(
    short_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Refresh Open Graph metadata by fetching from destination URL."""
    url = db.query(URL).filter(
        URL.short_code == short_code,
        URL.created_by == current_user.id,
    ).first()

    if not url:
        raise HTTPException(status_code=404, detail="URL not found")

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

        url.og_fetched_at = datetime.utcnow()
        db.commit()

    return {
        "og_title": url.og_title or url.title,
        "og_description": url.og_description,
        "og_image_url": url.og_image_url,
        "og_url": f"https://shurl.griddo.io/{short_code}",
        "has_custom_preview": bool(url.og_title or url.og_description or url.og_image_url),
        "fetched_at": url.og_fetched_at,
    }
```

---

### Task 5: Frontend Preview Components

**Effort**: 4-5 hours

#### Preview Card Component

Create `frontend/src/components/PreviewCard.astro`:

```astro
---
interface Props {
  title?: string;
  description?: string;
  imageUrl?: string;
  url: string;
}

const { title, description, imageUrl, url } = Astro.props;
---

<div class="preview-card">
  {imageUrl && (
    <div class="preview-image">
      <img src={imageUrl} alt={title || 'Preview'} />
    </div>
  )}

  <div class="preview-content">
    <h3 class="preview-title">{title || 'No title'}</h3>
    {description && (
      <p class="preview-description">{description}</p>
    )}
    <p class="preview-url">{url}</p>
  </div>
</div>

<style>
  .preview-card {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    overflow: hidden;
    max-width: 500px;
    background: white;
  }

  .preview-image {
    width: 100%;
    height: 250px;
    overflow: hidden;
    background: #f3f4f6;
  }

  .preview-image img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .preview-content {
    padding: 1rem;
  }

  .preview-title {
    font-size: 1.125rem;
    font-weight: 600;
    color: #111827;
    margin-bottom: 0.5rem;
  }

  .preview-description {
    font-size: 0.875rem;
    color: #6b7280;
    margin-bottom: 0.5rem;
    line-height: 1.5;
  }

  .preview-url {
    font-size: 0.75rem;
    color: #9ca3af;
    text-transform: uppercase;
  }
</style>
```

#### Add to URL Details Page

Update `frontend/src/pages/dashboard/urls/[code].astro`:

```astro
---
import PreviewCard from '@/components/PreviewCard.astro';

// ... existing code to fetch URL ...

const previewData = url.og_title || url.og_description || url.og_image_url
  ? {
      title: url.og_title || url.title,
      description: url.og_description,
      imageUrl: url.og_image_url,
    }
  : null;
---

<!-- Add preview section -->
<div class="mt-8">
  <div class="flex justify-between items-center mb-4">
    <h2 class="text-xl font-semibold">Social Media Preview</h2>
    <button id="refresh-preview" class="btn-secondary">
      Refresh from destination
    </button>
  </div>

  {previewData ? (
    <PreviewCard {...previewData} url={url.short_url} />
  ) : (
    <div class="text-center py-8 bg-gray-50 rounded-lg">
      <p class="text-gray-500 mb-4">No preview metadata available</p>
      <button id="fetch-preview" class="btn-primary">
        Fetch from destination
      </button>
    </div>
  )}
</div>

<script>
  // Handle refresh button
  document.getElementById('refresh-preview')?.addEventListener('click', async () => {
    const code = window.location.pathname.split('/').pop();
    const response = await apiPost(`/api/urls/${code}/refresh-preview`, {});
    if (response.ok) {
      window.location.reload();
    }
  });
</script>
```

---

## Success Criteria

✅ Social media crawlers see rich preview cards with title/image/description
✅ Regular users get instant redirects (no delay)
✅ Dashboard shows preview cards for all URLs
✅ Users can customize preview metadata
✅ Metadata auto-fetches from destination on URL creation
✅ All tests pass (20+ new tests for OG functionality)
✅ No breaking changes to existing URLs

---

## Notes

- **Backward Compatibility**: All new fields are optional/nullable to avoid breaking existing data
- **Performance**: Cursor pagination (Phase 5) can wait until user base grows
- **Security**: Rate limiting is critical - prioritize before public deployment
- **UX**: Title field has highest user-visible impact - implement first

**Next**: Review with stakeholders, then begin implementation!
