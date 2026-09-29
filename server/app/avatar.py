"""
Phase 3.12 — the avatar: the signed-in person's picture, kept in their profile.

- `PUT /auth/me/avatar` takes the image as the request body: a JPEG, PNG or WebP by its
  magic bytes, 2 MB at most, refused as it arrives rather than read whole first. It's
  stored re-encoded, without metadata (server/utils/avatar.py).
- `GET /auth/me/avatar` answers the stored WebP. The `?v=<avatar_version>` URL of the
  current version is immutable in the browser's cache; any other, the bare one included,
  is revalidated against the ETag. 404 without an avatar.
- `DELETE /auth/me/avatar` goes back to the initial.

The frontend fetches it with the bearer header and shows it through an object URL: a
plain <img src> can't send the header. None of it is an MCP tool (mcp_server/server.py).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import User, UserProfile
from server.schemas.profile import ProfileResponse
from server.schemas.responses import get_responses
from server.utils.avatar import (
    CONTENT_TYPE,
    MAX_UPLOAD_BYTES,
    TOO_BIG,
    AvatarRefused,
    normalize,
)
from server.utils.stored_image import IMAGE_SCHEMA, UPLOAD_BODY, image_response, read_capped

avatar_router = APIRouter()

NO_AVATAR = "No avatar"


@avatar_router.put(
    "/me/avatar",
    response_model=ProfileResponse,
    responses={
        200: {"description": "The profile, with the new `avatar_version`"},
        **get_responses(401),
        413: {"description": "More than 2 MB, or more than 4096 pixels a side"},
        415: {"description": "Not a readable JPEG, PNG or WebP"},
    },
    openapi_extra=UPLOAD_BODY,
)
async def upload_my_avatar(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Set your avatar: the image is the request body (JPEG, PNG or WebP, 2 MB at most).

    It's stored as a 512×512 WebP: turned as the photo was taken, cropped to its centre,
    and without metadata (no EXIF or GPS). Replaces the avatar there was.
    """
    data = await read_capped(request, MAX_UPLOAD_BYTES, TOO_BIG)
    try:
        avatar = await run_in_threadpool(normalize, data)
    except AvatarRefused as refused:
        raise HTTPException(refused.status_code, refused.detail) from None
    # The database work, and reading the saved row back, off the event loop.
    return await run_in_threadpool(_save, db, current_user, avatar)


def _save(db: Session, user: User, avatar: bytes) -> ProfileResponse:
    profile = user.profile
    if profile is None:
        profile = UserProfile(user=user)
        db.add(profile)
    profile.avatar = avatar
    profile.avatar_content_type = CONTENT_TYPE
    profile.avatar_updated_at = datetime.utcnow()
    db.commit()
    return ProfileResponse.model_validate(profile)


@avatar_router.get(
    "/me/avatar",
    response_class=Response,
    responses={
        200: {"description": "The avatar", "content": {CONTENT_TYPE: IMAGE_SCHEMA}},
        304: {"description": "Unchanged since the ETag sent in If-None-Match"},
        **get_responses(401, 404),
    },
)
def get_my_avatar(
    request: Request,
    v: str | None = None,
    current_user: User = Depends(get_current_user),
):
    """
    Your avatar, as stored (image/webp). 404 without one.

    Ask for `?v=<avatar_version>` (from `GET /auth/me`): that URL may stay in the browser's
    cache for good, since a new upload gets a new version. Any other URL is checked
    against the ETag each time.
    """
    profile = current_user.profile
    version = profile.avatar_version if profile is not None else None
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NO_AVATAR)
    return image_response(
        request, version, v, lambda: (profile.avatar, profile.avatar_content_type)
    )


@avatar_router.delete(
    "/me/avatar",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=get_responses(401),
)
def delete_my_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove your avatar: the initial shows again. Without one, nothing changes."""
    profile = current_user.profile
    if profile is not None and profile.avatar_updated_at is not None:
        profile.avatar = None
        profile.avatar_content_type = None
        profile.avatar_updated_at = None
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
