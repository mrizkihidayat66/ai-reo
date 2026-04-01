"""Database engine and session configuration."""

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from ai_reo.config import settings

logger = logging.getLogger(__name__)

# Safely expand `~` in SQLite URLs so they map to the correct user directory
# rather than creating a literal `~` folder in the current directory.
db_url = settings.database.database_url
if db_url.startswith("sqlite:///~/"):
    expanded_path = Path.home() / db_url[len("sqlite:///~/") :]
    # Ensure the parent directory exists
    expanded_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{expanded_path}"

# SQLite requires check_same_thread=False when sharing across FastAPI async loops
connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}

try:
    engine = create_engine(db_url, connect_args=connect_args)
    logger.debug("Database engine initialized against %s", db_url)
except Exception as exc:
    logger.error("Failed to initialize database engine: %s", exc)
    raise

# Factory for obtaining new database sessions
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative base class for our models
Base = declarative_base()


def get_db() -> Iterator[Session]:
    """FastAPI dependency for yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session():
    """Context manager for DB operations outside FastAPI's DI system.

    Use this inside agents, services, and anywhere that isn't a FastAPI
    route handler with ``Depends(get_db)``.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
