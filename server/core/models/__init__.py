"""Database models for Shurly."""

from server.core.models.campaign import Campaign
from server.core.models.tag import Tag, url_tags, campaign_tags
from server.core.models.url import URL, URLType
from server.core.models.user import ApiKeyScope, User
from server.core.models.visitor import Visitor

__all__ = [
    "User",
    "ApiKeyScope",
    "URL",
    "URLType",
    "Campaign",
    "Visitor",
    "Tag",
    "url_tags",
    "campaign_tags",
]
