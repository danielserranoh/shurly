from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from server.core.config import settings

# Create singleton engine with Lambda-aware configuration
# When running in Lambda, use smaller connection pool to avoid overwhelming RDS
engine = create_engine(
    settings.database_url,
    pool_recycle=settings.db_pool_recycle,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,  # Verify connections before using (important for Lambda)
    echo=False,  # Set to True for SQL logging during development
    connect_args={
        "sslmode": settings.db_ssl_mode,  # SSL mode for RDS connections
    } if settings.db_ssl_mode else {},
)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for models
Base = declarative_base()


def get_db() -> Session:
    """
    Dependency function for FastAPI to get database session.

    Usage in routes:
        @app.get("/items")
        def read_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create all tables in the database."""
    Base.metadata.create_all(bind=engine)


def drop_tables():
    """Drop all tables in the database (use with caution!)."""
    Base.metadata.drop_all(bind=engine)
