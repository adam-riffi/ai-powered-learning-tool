"""SQLAlchemy engine, session management, and DB initialisation."""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config import get_database_url
from models import Base


def _build_engine():
    """Build a new engine reading DATABASE_URL at call time."""
    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
    )


def init_db() -> None:
    """Create all tables. Safe to call multiple times (idempotent)."""
    engine = _build_engine()
    Base.metadata.create_all(bind=engine)
    engine.dispose()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Yield a database session, committing on success and rolling back on error.

    Usage:
        with get_db() as db:
            db.add(some_object)
    """
    engine = _build_engine()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        engine.dispose()