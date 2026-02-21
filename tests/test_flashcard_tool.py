"""Tests for manage_flashcards (flashcard_tool).

Run with:
    pytest tests/test_flashcard_tool.py -v
"""
import pytest
from tools.lesson_generator import manage_curriculum
from tools.flashcard_tool import manage_flashcards


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------

def setup_lesson(override_db) -> tuple[int, int, int]:
    """Create course → module → lesson. Returns (course_id, module_id, lesson_id)."""
    course = manage_curriculum(
        action="create_course",
        title="Test Course",
        topic="Testing",
        level="beginner",
        goal="Test things",
        hours_per_week=3,
    )
    module = manage_curriculum(
        action="add_module",
        course_id=course["id"],
        title="Module 1",
        order_index=0,
    )
    lesson = manage_curriculum(
        action="add_lesson",
        module_id=module["id"],
        title="Lesson 1",
        order_index=0,
        tags=["python"],
    )
    return course["id"], module["id"], lesson["id"]


SAMPLE_CARDS = [
    {"front": "What is a variable?", "back": "A named storage location.", "tags": ["python"]},
    {"front": "What is a loop?", "back": "Repeated execution of code.", "tags": ["python", "control-flow"]},
    {"front": "What is a function?", "back": "A reusable block of code.", "tags": ["python"]},
]


# ---------------------------------------------------------------------------
# Tests: create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_creates_cards_and_returns_count(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        result = manage_flashcards(action="create", lesson_id=lesson_id, cards=SAMPLE_CARDS)

        assert result["created"] == 3
        assert len(result["flashcards"]) == 3
        assert result["flashcards"][0]["lesson_id"] == lesson_id

    def test_card_fields_stored_correctly(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        result = manage_flashcards(action="create", lesson_id=lesson_id, cards=[SAMPLE_CARDS[0]])

        card = result["flashcards"][0]
        assert card["front"] == "What is a variable?"
        assert card["back"] == "A named storage location."
        assert card["tags"] == ["python"]

    def test_empty_cards_raises(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        with pytest.raises(ValueError, match="non-empty"):
            manage_flashcards(action="create", lesson_id=lesson_id, cards=[])

    def test_card_missing_front_raises(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        with pytest.raises(ValueError, match="front"):
            manage_flashcards(action="create", lesson_id=lesson_id, cards=[{"back": "answer"}])

    def test_invalid_lesson_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_flashcards(action="create", lesson_id=9999, cards=SAMPLE_CARDS)


# ---------------------------------------------------------------------------
# Tests: list
# ---------------------------------------------------------------------------

class TestList:
    def test_list_by_lesson(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        manage_flashcards(action="create", lesson_id=lesson_id, cards=SAMPLE_CARDS)

        result = manage_flashcards(action="list", lesson_id=lesson_id)
        assert result["total"] == 3

    def test_list_by_course(self, override_db):
        course_id, _, lesson_id = setup_lesson(override_db)
        manage_flashcards(action="create", lesson_id=lesson_id, cards=SAMPLE_CARDS)

        result = manage_flashcards(action="list", course_id=course_id)
        assert result["total"] == 3

    def test_list_with_tag_filter(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        manage_flashcards(action="create", lesson_id=lesson_id, cards=SAMPLE_CARDS)

        # "control-flow" tag is only on the second card
        result = manage_flashcards(action="list", lesson_id=lesson_id, tags=["control-flow"])
        assert result["total"] == 1
        assert result["flashcards"][0]["front"] == "What is a loop?"

    def test_list_requires_lesson_or_course(self, override_db):
        with pytest.raises(ValueError, match="Provide at least one"):
            manage_flashcards(action="list")

    def test_empty_lesson_returns_zero(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        result = manage_flashcards(action="list", lesson_id=lesson_id)
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Tests: get
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_single_card(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        created = manage_flashcards(action="create", lesson_id=lesson_id, cards=[SAMPLE_CARDS[0]])
        card_id = created["flashcards"][0]["id"]

        result = manage_flashcards(action="get", flashcard_id=card_id)
        assert result["id"] == card_id
        assert result["front"] == "What is a variable?"

    def test_get_invalid_id_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_flashcards(action="get", flashcard_id=9999)


# ---------------------------------------------------------------------------
# Tests: delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_by_lesson(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        manage_flashcards(action="create", lesson_id=lesson_id, cards=SAMPLE_CARDS)

        result = manage_flashcards(action="delete", lesson_id=lesson_id)
        assert result["deleted"] == 3

        # Verify deletion
        remaining = manage_flashcards(action="list", lesson_id=lesson_id)
        assert remaining["total"] == 0

    def test_delete_single_card(self, override_db):
        _, _, lesson_id = setup_lesson(override_db)
        created = manage_flashcards(action="create", lesson_id=lesson_id, cards=SAMPLE_CARDS)
        card_id = created["flashcards"][0]["id"]

        result = manage_flashcards(action="delete", flashcard_id=card_id)
        assert result["deleted"] == 1

        remaining = manage_flashcards(action="list", lesson_id=lesson_id)
        assert remaining["total"] == 2

    def test_delete_requires_lesson_or_flashcard_id(self, override_db):
        with pytest.raises(ValueError, match="Provide at least one"):
            manage_flashcards(action="delete")

    def test_delete_invalid_flashcard_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_flashcards(action="delete", flashcard_id=9999)


# ---------------------------------------------------------------------------
# Tests: unknown action
# ---------------------------------------------------------------------------

def test_unknown_action_raises(override_db):
    with pytest.raises(ValueError, match="Unknown action"):
        manage_flashcards(action="explode")
