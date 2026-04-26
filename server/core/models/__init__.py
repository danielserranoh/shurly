"""Database models for Shurly."""

from server.core.models.campaign import Campaign
from server.core.models.domain import Domain
from server.core.models.orphan_visit import OrphanVisit, OrphanVisitType
from server.core.models.redirect_rule import RedirectRule
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
    "Domain",
    "OrphanVisit",
    "OrphanVisitType",
    "RedirectRule",
    "Visitor",
    "Tag",
    "url_tags",
    "campaign_tags",
]
