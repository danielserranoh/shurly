"""
Phase 5.8 — the MCP OAuth proxy's state, in the database (table `mcp_oauth_store`).

fastmcp's OAuth proxy keeps client registrations, sign-ins in progress, consent
tokens, authorization codes, Google's tokens and the map from its tokens to
Google's in a py-key-value store, by default encrypted files on the task's disk.
Up to two tasks serve the MCP with no affinity, and every deploy replaces them,
so it lives in the database instead, shared by every task.

Values are encrypted with a key derived from MCP_OAUTH_SIGNING_KEY, as fastmcp
does for its own file store: Google's refresh tokens are among them.

Not py-key-value's PostgreSQLStore: it needs asyncpg (a second driver and pool)
and creates its table at runtime, outside the migrations.
"""

from datetime import datetime, timezone

import anyio.to_thread
from cryptography.fernet import Fernet
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from key_value.aio._utils.managed_entry import ManagedEntry, load_from_json
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.base import BaseStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, sessionmaker

from server.core.models import McpOAuthEntry


def _naive_utc(moment: datetime | None) -> datetime | None:
    """The columns hold naive UTC, like every other in the schema."""
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _aware_utc(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=timezone.utc) if moment is not None else None


class DatabaseStore(BaseStore):
    """py-key-value's store interface on our database, one short session per call."""

    def __init__(self, session_factory: sessionmaker, **kwargs):
        super().__init__(stable_api=True, **kwargs)
        self._session_factory = session_factory

    async def _get_managed_entry(self, *, collection: str, key: str) -> ManagedEntry | None:
        return await anyio.to_thread.run_sync(self._get, collection, key)

    async def _put_managed_entry(
        self, *, collection: str, key: str, managed_entry: ManagedEntry
    ) -> None:
        await anyio.to_thread.run_sync(self._put, collection, key, managed_entry)

    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        return await anyio.to_thread.run_sync(self._delete, collection, key)

    def _get(self, collection: str, key: str) -> ManagedEntry | None:
        with self._session_factory() as db:
            row = db.get(McpOAuthEntry, (collection, key))
            if row is None:
                return None
            return ManagedEntry(
                value=load_from_json(row.value),
                created_at=_aware_utc(row.created_at),
                expires_at=_aware_utc(row.expires_at),
            )

    def _put(self, collection: str, key: str, entry: ManagedEntry) -> None:
        values = {
            "collection": collection,
            "key": key,
            "value": entry.value_as_json,
            "created_at": _naive_utc(entry.created_at),
            "expires_at": _naive_utc(entry.expires_at),
        }
        with self._session_factory() as db:
            # Expired rows read as missing already; this is only housekeeping.
            db.execute(delete(McpOAuthEntry).where(McpOAuthEntry.expires_at < _naive_utc(_now())))
            db.execute(_upsert(db, values))
            db.commit()

    def _delete(self, collection: str, key: str) -> bool:
        with self._session_factory() as db:
            result = db.execute(
                delete(McpOAuthEntry).where(
                    McpOAuthEntry.collection == collection, McpOAuthEntry.key == key
                )
            )
            db.commit()
            return result.rowcount > 0


def _upsert(db: Session, values: dict):
    """INSERT … ON CONFLICT DO UPDATE: two tasks writing one key can't collide."""
    insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
    statement = insert(McpOAuthEntry).values(**values)
    return statement.on_conflict_do_update(
        index_elements=["collection", "key"],
        set_={name: statement.excluded[name] for name in ("value", "created_at", "expires_at")},
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def encrypted_database_store(session_factory: sessionmaker, signing_key: str) -> AsyncKeyValue:
    """The store to give the OAuth proxy: in the database, encrypted.

    The key is derived from MCP_OAUTH_SIGNING_KEY with its own salt, so the
    signing and encryption keys differ. A value that doesn't decrypt (after the
    setting changed) reads as missing, as fastmcp does: clients sign in again.
    """
    key = derive_jwt_key(high_entropy_material=signing_key, salt="shurly-mcp-oauth-storage")
    return FernetEncryptionWrapper(
        key_value=DatabaseStore(session_factory),
        fernet=Fernet(key),
        raise_on_decryption_error=False,
    )
