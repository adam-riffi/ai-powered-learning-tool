"""Shared pytest fixtures.

All tests use an in-memory SQLite database so no files are written to disk
and every test runs in full isolation.

The key mechanism: override_db monkeypatches database.get_db so that
every tool call uses the test session instead of the real database.
"""
import sys
import os
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Base


@pytest.fixture(scope="session")
def engine():
    """Create a shared in-memory SQLite engine for the test session."""
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
    Each test runs inside a transaction that is rolled back on teardown,
    so tests never share state.
    """
    connection = engine.connect()
    transaction = connection.begin()

    _SessionLocal = sessionmaker(bind=connection, autocommit=False, autoflush=False)
    session = _SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


def _make_fake_get_db(session):
    """Return a context manager that yields the given test session."""
    @contextmanager
    def _fake_get_db():
        try:
            yield session
            session.flush()
        except Exception:
            session.rollback()
            raise
    return _fake_get_db


@pytest.fixture()
def override_db(db_session, monkeypatch):
    """
    Patch database.get_db so all tool calls use the in-memory test session.

    Usage:
        def test_something(override_db):
            result = manage_curriculum(action="list_courses")
            ...
    """
    fake_get_db = _make_fake_get_db(db_session)

    import database
    import tools.lesson_generator as lg
    import tools.flashcard_tool as ft
    import tools.quiz_tool as qt

    monkeypatch.setattr(database, "get_db", fake_get_db)
    monkeypatch.setattr(lg, "get_db", fake_get_db)
    monkeypatch.setattr(ft, "get_db", fake_get_db)
    monkeypatch.setattr(qt, "get_db", fake_get_db)

    yield db_session


@pytest.fixture()
def mock_notion(monkeypatch):
    """
    Replace the Notion client with a MagicMock so tests run without a real API key.
    Returns the mock so individual tests can configure return values.
    """
    from unittest.mock import MagicMock

    mock_client = MagicMock()
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

    yield mock_client


@pytest.fixture()
def override_db_for_notion(db_session, monkeypatch):
    """Patch database.get_db inside notion_tool for Notion-specific tests."""
    fake_get_db = _make_fake_get_db(db_session)

    import tools.notion_tool as nt
    monkeypatch.setattr(nt, "get_db", fake_get_db)

    yield db_session