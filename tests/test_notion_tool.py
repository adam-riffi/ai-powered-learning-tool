"""Tests for manage_notion_page (notion_tool).

All Notion API calls are mocked — no real API key or network needed.

Run with:
    pytest tests/test_notion_tool.py -v
"""
import pytest
from unittest.mock import MagicMock
from tools.lesson_generator import manage_curriculum
from tools.notion_tool import manage_notion_page


# ---------------------------------------------------------------------------
# Setup helper
# ---------------------------------------------------------------------------

def setup_course_with_content(override_db_for_notion) -> int:
    """Creates a course with one module and two lessons. Returns course_id."""
    course = manage_curriculum(
        action="create_course",
        title="Notion Test Course",
        topic="Testing",
        level="intermediate",
        goal="Test Notion integration",
        hours_per_week=3,
    )
    module = manage_curriculum(
        action="add_module",
        course_id=course["id"],
        title="Module One",
        order_index=0,
        description="First module",
    )
    manage_curriculum(
        action="add_lesson",
        module_id=module["id"],
        title="Lesson Alpha",
        order_index=0,
        objective="Learn alpha",
        content="Alpha content.",
        tags=["alpha"],
    )
    manage_curriculum(
        action="add_lesson",
        module_id=module["id"],
        title="Lesson Beta",
        order_index=1,
        objective="Learn beta",
        content="Beta content.",
        tags=["beta"],
    )
    return course["id"]


# ---------------------------------------------------------------------------
# Tests: publish_course
# ---------------------------------------------------------------------------

class TestPublishCourse:
    def test_publishes_course_and_returns_ids(
        self, override_db_for_notion, mock_notion, monkeypatch
    ):
        # Wire the DB fixture for notion_tool as well
        import tools.notion_tool as nt
        from contextlib import contextmanager

        @contextmanager
        def _fake_get_db():
            yield override_db_for_notion
            override_db_for_notion.flush()

        monkeypatch.setattr(nt, "get_db", _fake_get_db)

        # Setup mock return values for sequential calls
        mock_notion.pages.create.side_effect = [
            {"id": "course-page-id"},    # course page
            {"id": "module-page-id"},    # module entry
            {"id": "lesson-alpha-id"},   # lesson Alpha
            {"id": "lesson-beta-id"},    # lesson Beta
        ]
        mock_notion.databases.create.return_value = {"id": "db-id-123"}

        course_id = setup_course_with_content(override_db_for_notion)
        result = manage_notion_page(action="publish_course", course_id=course_id)

        assert result["course_page_id"] == "course-page-id"
        assert result["database_id"] == "db-id-123"
        assert result["pages_created"] == 3  # 1 module + 2 lessons

    def test_invalid_course_raises(self, override_db_for_notion, mock_notion, monkeypatch):
        import tools.notion_tool as nt
        from contextlib import contextmanager

        @contextmanager
        def _fake_get_db():
            yield override_db_for_notion
            override_db_for_notion.flush()

        monkeypatch.setattr(nt, "get_db", _fake_get_db)

        with pytest.raises(ValueError, match="not found"):
            manage_notion_page(action="publish_course", course_id=9999)


# ---------------------------------------------------------------------------
# Tests: query_page
# ---------------------------------------------------------------------------

class TestQueryPage:
    def test_query_returns_page_metadata(self, override_db_for_notion, mock_notion):
        mock_notion.pages.retrieve.return_value = {
            "id": "page-123",
            "properties": {"Name": {"title": [{"plain_text": "Test Page"}]}},
            "archived": False,
        }

        result = manage_notion_page(action="query_page", page_id="page-123")
        assert result["id"] == "page-123"
        mock_notion.pages.retrieve.assert_called_once_with(page_id="page-123")


# ---------------------------------------------------------------------------
# Tests: update_page
# ---------------------------------------------------------------------------

class TestUpdatePage:
    def test_update_calls_notion_api(self, override_db_for_notion, mock_notion):
        mock_notion.pages.update.return_value = {"id": "page-123", "archived": False}

        props = {"Status": {"select": {"name": "Completed"}}}
        result = manage_notion_page(action="update_page", page_id="page-123", properties=props)

        mock_notion.pages.update.assert_called_once_with(page_id="page-123", properties=props)
        assert result["id"] == "page-123"


# ---------------------------------------------------------------------------
# Tests: delete_page
# ---------------------------------------------------------------------------

class TestDeletePage:
    def test_archives_page(self, override_db_for_notion, mock_notion):
        result = manage_notion_page(action="delete_page", page_id="page-to-delete")

        mock_notion.pages.update.assert_called_once_with(
            page_id="page-to-delete", archived=True
        )
        assert result["archived"] is True
        assert result["page_id"] == "page-to-delete"


# ---------------------------------------------------------------------------
# Tests: sync_status
# ---------------------------------------------------------------------------

class TestSyncStatus:
    def test_unsynced_when_not_published(self, override_db_for_notion, mock_notion, monkeypatch):
        import tools.notion_tool as nt
        from contextlib import contextmanager

        @contextmanager
        def _fake_get_db():
            yield override_db_for_notion
            override_db_for_notion.flush()

        monkeypatch.setattr(nt, "get_db", _fake_get_db)

        course_id = setup_course_with_content(override_db_for_notion)
        result = manage_notion_page(action="sync_status", course_id=course_id)

        assert len(result["unsynced"]) == 2
        assert len(result["synced"]) == 0
        assert result["last_synced_at"] is None

    def test_invalid_course_raises(self, override_db_for_notion, mock_notion, monkeypatch):
        import tools.notion_tool as nt
        from contextlib import contextmanager

        @contextmanager
        def _fake_get_db():
            yield override_db_for_notion
            override_db_for_notion.flush()

        monkeypatch.setattr(nt, "get_db", _fake_get_db)

        with pytest.raises(ValueError, match="not found"):
            manage_notion_page(action="sync_status", course_id=9999)


# ---------------------------------------------------------------------------
# Tests: missing Notion credentials
# ---------------------------------------------------------------------------

class TestMissingCredentials:
    def test_raises_without_api_key(self, override_db_for_notion, monkeypatch):
        """Ensure a helpful error is raised when NOTION_API_KEY is not set."""
        import tools.notion_tool as nt

        # Remove the mock so the real _get_notion_client is called
        monkeypatch.undo()

        from config import settings
        monkeypatch.setattr(settings, "notion_api_key", None)

        # Re-import to pick up the real function
        from tools.notion_tool import _get_notion_client

        with pytest.raises(RuntimeError, match="NOTION_API_KEY"):
            _get_notion_client()


# ---------------------------------------------------------------------------
# Tests: unknown action
# ---------------------------------------------------------------------------

def test_unknown_action_raises(override_db_for_notion, mock_notion):
    with pytest.raises(ValueError, match="Unknown action"):
        manage_notion_page(action="beam_me_up")
