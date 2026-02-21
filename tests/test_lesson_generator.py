"""Tests for manage_curriculum (lesson_generator tool).

Run these tests with:
    pytest tests/test_lesson_generator.py -v

Each test is fully isolated — an in-memory SQLite DB is rolled back after every test.
"""
import pytest
from tools.lesson_generator import manage_curriculum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_course(override_db, **overrides) -> dict:
    kwargs = dict(
        title="Python Basics",
        topic="Python",
        level="beginner",
        goal="Write simple Python scripts",
        hours_per_week=5,
    )
    kwargs.update(overrides)
    return manage_curriculum(action="create_course", **kwargs)


def make_module(override_db, course_id: int, title="Module 1", order_index=0) -> dict:
    return manage_curriculum(
        action="add_module",
        course_id=course_id,
        title=title,
        order_index=order_index,
        description="First module",
    )


def make_lesson(
    override_db,
    module_id: int,
    title="What is a variable?",
    order_index=0,
) -> dict:
    return manage_curriculum(
        action="add_lesson",
        module_id=module_id,
        title=title,
        order_index=order_index,
        objective="Understand variables",
        content="A variable stores a value.",
        tags=["python", "variables"],
    )


# ---------------------------------------------------------------------------
# Tests: create_course
# ---------------------------------------------------------------------------

class TestCreateCourse:
    def test_returns_course_with_id(self, override_db):
        course = make_course(override_db)
        assert "id" in course
        assert course["title"] == "Python Basics"
        assert course["level"] == "beginner"
        assert course["status"] == "draft"

    def test_invalid_level_raises(self, override_db):
        with pytest.raises(ValueError, match="Invalid level"):
            manage_curriculum(
                action="create_course",
                title="X", topic="X", level="expert",
                goal="...", hours_per_week=3,
            )

    def test_multiple_courses(self, override_db):
        make_course(override_db, title="Course A")
        make_course(override_db, title="Course B")
        result = manage_curriculum(action="list_courses")
        assert result["total"] >= 2


# ---------------------------------------------------------------------------
# Tests: add_module
# ---------------------------------------------------------------------------

class TestAddModule:
    def test_creates_module(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        assert module["course_id"] == course["id"]
        assert module["title"] == "Module 1"

    def test_invalid_course_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_curriculum(action="add_module", course_id=9999, title="X", order_index=0)


# ---------------------------------------------------------------------------
# Tests: add_lesson
# ---------------------------------------------------------------------------

class TestAddLesson:
    def test_creates_lesson_with_empty_flashcards(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        lesson = make_lesson(override_db, module_id=module["id"])

        assert lesson["module_id"] == module["id"]
        assert lesson["title"] == "What is a variable?"
        assert lesson["tags"] == ["python", "variables"]
        assert lesson["flashcards"] == []  # signal to create flashcards next

    def test_lesson_without_optional_fields(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        lesson = manage_curriculum(
            action="add_lesson",
            module_id=module["id"],
            title="Minimal Lesson",
            order_index=0,
        )
        assert lesson["objective"] is None
        assert lesson["content"] is None
        assert lesson["tags"] == []

    def test_invalid_module_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_curriculum(action="add_lesson", module_id=9999, title="X", order_index=0)


# ---------------------------------------------------------------------------
# Tests: update_lesson
# ---------------------------------------------------------------------------

class TestUpdateLesson:
    def test_updates_content(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        lesson = make_lesson(override_db, module_id=module["id"])

        updated = manage_curriculum(
            action="update_lesson",
            lesson_id=lesson["id"],
            content="Updated content.",
            is_completed=True,
        )
        assert updated["content"] == "Updated content."
        assert updated["is_completed"] is True

    def test_partial_update_does_not_clear_other_fields(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        lesson = make_lesson(override_db, module_id=module["id"])

        updated = manage_curriculum(
            action="update_lesson",
            lesson_id=lesson["id"],
            title="New Title",
        )
        # Tags should be preserved
        assert updated["tags"] == ["python", "variables"]
        assert updated["title"] == "New Title"

    def test_invalid_lesson_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_curriculum(action="update_lesson", lesson_id=9999, title="X")


# ---------------------------------------------------------------------------
# Tests: get_course
# ---------------------------------------------------------------------------

class TestGetCourse:
    def test_returns_full_tree(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        make_lesson(override_db, module_id=module["id"])

        result = manage_curriculum(action="get_course", course_id=course["id"])
        assert len(result["modules"]) == 1
        assert len(result["modules"][0]["lessons"]) == 1
        assert "flashcard_count" in result["modules"][0]["lessons"][0]

    def test_invalid_course_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_curriculum(action="get_course", course_id=9999)


# ---------------------------------------------------------------------------
# Tests: list_courses
# ---------------------------------------------------------------------------

class TestListCourses:
    def test_empty_when_no_courses(self, override_db):
        result = manage_curriculum(action="list_courses")
        assert result["total"] == 0
        assert result["courses"] == []

    def test_includes_summary_stats(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        make_lesson(override_db, module_id=module["id"])

        result = manage_curriculum(action="list_courses")
        assert result["total"] == 1
        assert result["courses"][0]["module_count"] == 1
        assert result["courses"][0]["lesson_count"] == 1


# ---------------------------------------------------------------------------
# Tests: delete_course
# ---------------------------------------------------------------------------

class TestDeleteCourse:
    def test_deletes_course_and_children(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        make_lesson(override_db, module_id=module["id"])

        result = manage_curriculum(action="delete_course", course_id=course["id"])
        assert result["deleted"] is True

        # Course should no longer exist
        with pytest.raises(ValueError):
            manage_curriculum(action="get_course", course_id=course["id"])

    def test_invalid_course_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_curriculum(action="delete_course", course_id=9999)


# ---------------------------------------------------------------------------
# Tests: search_lessons
# ---------------------------------------------------------------------------

class TestSearchLessons:
    def test_finds_by_title(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        make_lesson(override_db, module_id=module["id"], title="All About Loops")

        result = manage_curriculum(action="search_lessons", query="Loops")
        assert result["total"] == 1
        assert "Loops" in result["lessons"][0]["title"]

    def test_finds_by_content(self, override_db):
        course = make_course(override_db)
        module = make_module(override_db, course_id=course["id"])
        manage_curriculum(
            action="add_lesson",
            module_id=module["id"],
            title="Lesson X",
            order_index=0,
            content="This lesson covers recursion in depth.",
        )

        result = manage_curriculum(action="search_lessons", query="recursion")
        assert result["total"] == 1

    def test_no_results_returns_empty(self, override_db):
        result = manage_curriculum(action="search_lessons", query="zzznomatch")
        assert result["total"] == 0

    def test_course_filter_restricts_scope(self, override_db):
        course_a = make_course(override_db, title="Course A")
        module_a = make_module(override_db, course_id=course_a["id"])
        make_lesson(override_db, module_id=module_a["id"], title="Loops in A")

        course_b = make_course(override_db, title="Course B")
        module_b = make_module(override_db, course_id=course_b["id"])
        make_lesson(override_db, module_id=module_b["id"], title="Loops in B")

        result = manage_curriculum(
            action="search_lessons", query="Loops", course_id=course_a["id"]
        )
        assert result["total"] == 1
        assert "A" in result["lessons"][0]["title"]


# ---------------------------------------------------------------------------
# Tests: unknown action
# ---------------------------------------------------------------------------

def test_unknown_action_raises(override_db):
    with pytest.raises(ValueError, match="Unknown action"):
        manage_curriculum(action="fly_to_moon")
