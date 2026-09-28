"""
Phase 5.8 — what the MCP's OAuth proxy (fastmcp) keeps between requests: client
registrations, sign-ins in progress, consent tokens, authorization codes, Google's
tokens and the map from the proxy's tokens to Google's.

In the database, not in a task's memory or disk: up to two tasks serve the MCP
behind the ALB, with no affinity, and every deploy replaces them. Keys and
collections are fastmcp's; values are encrypted (mcp_server/oauth_store.py).
"""

from sqlalchemy import Column, DateTime, String, Text

from server.core import Base


class McpOAuthEntry(Base):
    __tablename__ = "mcp_oauth_store"

    collection = Column(String(128), primary_key=True)
    key = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=True)
    # Expired rows read as missing, and go when the store next writes.
    expires_at = Column(DateTime, nullable=True, index=True)
