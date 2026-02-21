"""Shared pytest fixtures.

All tests use an in-memory SQLite database so no file is created on disk
and tests are fully isolated from each other.

The key trick: `override_db` monkeypatches `database.get_db` so that
every tool call uses the in-memory session instead of the real DB.
"""
import pytest
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

import sys
import os
# Ensure the project root is on the path regardless of how pytest is invoked
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Base


# ---------------------------------------------------------------------------
# In-memory database engine (shared across all fixtures in a test session)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine():
    """Create an in-memory SQLite engine once per test session."""
    _engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=_engine)
    yield _engine
    _engine.dispose()


@pytest.fixture()
def db_session(engine):
    """
    Provide a clean database session for each test.
    Wraps the test in a transaction that is rolled back after the test,
    keeping tests fully isolated.
    """
    connection = engine.connect()
    transaction = connection.begin()

    _SessionLocal = sessionmaker(bind=connection, autocommit=False, autoflush=False)
    session = _SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Monkeypatch: replace database.get_db with our in-memory session
# ---------------------------------------------------------------------------

@pytest.fixture()
def override_db(db_session, monkeypatch):
    """
    Patch `database.get_db` so all tool calls use the in-memory test session.

    Usage:
        def test_something(override_db):
            result = manage_curriculum(action="list_courses")
            ...
    """
    @contextmanager
    def _fake_get_db():
        try:
            yield db_session
            db_session.flush()
        except Exception:
            db_session.rollback()
            raise

    import database
    monkeypatch.setattr(database, "get_db", _fake_get_db)

    # Also patch the import inside each tool module (they do `from database import get_db`)
    import tools.lesson_generator as lg
    import tools.flashcard_tool as ft
    import tools.quiz_tool as qt

    monkeypatch.setattr(lg, "get_db", _fake_get_db)
    monkeypatch.setattr(ft, "get_db", _fake_get_db)
    monkeypatch.setattr(qt, "get_db", _fake_get_db)

    yield db_session


@pytest.fixture()
def mock_notion(monkeypatch):
    """
    Patch notion_client.Client so Notion tests work without a real API key.
    Returns a MagicMock that you can configure in individual tests.
    """
    from unittest.mock import MagicMock, patch

    mock_client = MagicMock()

    # Default return values for common Notion API calls
    mock_client.pages.create.return_value = {"id": "notion-page-id-123"}
    mock_client.databases.create.return_value = {"id": "notion-db-id-456"}
    mock_client.pages.retrieve.return_value = {
        "id": "notion-page-id-123",
        "properties": {},
        "archived": False,
    }
    mock_client.pages.update.return_value = {
        "id": "notion-page-id-123",
        "archived": False,
    }

    import tools.notion_tool as nt
    monkeypatch.setattr(nt, "_get_notion_client", lambda: mock_client)

    # Also patch the DB for Notion tests
    yield mock_client


@pytest.fixture()
def override_db_for_notion(db_session, monkeypatch):
    """Combined fixture for Notion tests: patches both DB and Notion client."""
    @contextmanager
    def _fake_get_db():
        try:
            yield db_session
            db_session.flush()
        except Exception:
            db_session.rollback()
            raise

    import tools.notion_tool as nt
    monkeypatch.setattr(nt, "get_db", _fake_get_db)

    yield db_session
