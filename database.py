"""SQLAlchemy engine, session management, and DB initialisation."""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config import settings
from models import Base

engine = create_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),
    connect_args={"check_same_thread": False} if settings.is_sqlite else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables. Safe to call multiple times (idempotent)."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """
    Yield a database session, committing on success and rolling back on error.

    Usage:
        with get_db() as db:
            db.add(some_object)
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
