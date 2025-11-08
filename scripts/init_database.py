#!/usr/bin/env python3
"""
Initialize Shurly database tables.

This script creates all necessary database tables using SQLAlchemy models.
Normally, tables are auto-created on first Lambda invocation, but this script
allows you to initialize the database before deployment.

Usage:
    python scripts/init_database.py <db_host> <db_password>

Example:
    python scripts/init_database.py shurly-dev-db.xxx.rds.amazonaws.com mypassword
"""

import sys
import os

# Add parent directory to path to import server modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from server.core.models.user import User
from server.core.models.url import URL
from server.core.models.visitor import Visitor
from server.core.models.campaign import Campaign
from server.core import Base


def init_database(db_host: str, db_password: str, db_name: str = "shurly", db_user: str = "postgres"):
    """Initialize database with all tables."""

    # Construct database URL
    db_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:5432/{db_name}?sslmode=require"

    print(f"Connecting to database at {db_host}...")

    try:
        # Create engine
        engine = create_engine(
            db_url,
            echo=True,  # Show SQL statements
            pool_pre_ping=True
        )

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"\n✓ Connected to PostgreSQL!")
            print(f"  Version: {version}\n")

        # Create all tables
        print("Creating tables...")
        Base.metadata.create_all(bind=engine)

        print("\n✓ Database initialization complete!")
        print("\nCreated tables:")
        print("  - users")
        print("  - urls")
        print("  - campaigns")
        print("  - visitors")

        # Verify tables exist
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
            """))
            tables = [row[0] for row in result]

            print("\nVerified tables in database:")
            for table in tables:
                print(f"  ✓ {table}")

        print("\n✅ Database is ready for use!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("  - Verify the RDS endpoint is correct")
        print("  - Check the password")
        print("  - Ensure the security group allows your IP on port 5432")
        print("  - Wait a few minutes if the RDS instance just became available")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/init_database.py <db_host> <db_password> [db_name] [db_user]")
        print("\nExample:")
        print("  python scripts/init_database.py shurly-dev-db.xxx.rds.amazonaws.com mypassword")
        sys.exit(1)

    db_host = sys.argv[1]
    db_password = sys.argv[2]
    db_name = sys.argv[3] if len(sys.argv) > 3 else "shurly"
    db_user = sys.argv[4] if len(sys.argv) > 4 else "postgres"

    init_database(db_host, db_password, db_name, db_user)
