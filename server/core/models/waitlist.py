"""
Phase 9.1 — the waitlist: people outside Griddo who'd like Shurly, and whether they come as an
individual or for a company.

One row per email (normalized to lowercase): signing up again updates it. What a person typed,
when they agreed to be contacted, and nothing about their connection: no IP, no user agent.
Kept until its person asks to be removed, or 24 months after their last sign-up
(docs/PERSONAL_DATA.md § The waitlist).
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from server.core import Base

KINDS = ("individual", "company")
COMPANY_SIZES = ("1-10", "11-50", "51-200", "201-1000", "1000+")

# The longest values each column holds; the request schema checks them (server/schemas/waitlist.py).
EMAIL_LENGTH = 254  # RFC 5321's longest path, less its angle brackets
NAME_LENGTH = 200
COMPANY_LENGTH = 200
ROLE_LENGTH = 120
USE_CASE_LENGTH = 1000
SOURCE_LENGTH = 100


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(EMAIL_LENGTH), nullable=False, unique=True)
    name = Column(String(NAME_LENGTH), nullable=False)
    # "individual" or "company" (KINDS); plain strings, so a new one needs no enum migration.
    kind = Column(String(16), nullable=False)
    # A company's name, and its size (COMPANY_SIZES), or none given. Always None for an individual.
    company = Column(String(COMPANY_LENGTH), nullable=True)
    company_size = Column(String(16), nullable=True)
    role = Column(String(ROLE_LENGTH), nullable=True)
    use_case = Column(String(USE_CASE_LENGTH), nullable=True)
    # How they heard about Shurly.
    source = Column(String(SOURCE_LENGTH), nullable=True)
    # When they agreed to be contacted about Shurly: the latest sign-up's.
    consent_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    # When the same email signed up again, with the answers it has now.
    updated_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<WaitlistEntry(id={self.id}, kind={self.kind})>"
