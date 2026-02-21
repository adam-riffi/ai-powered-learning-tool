"""Tests for manage_quiz (quiz_tool).

Run with:
    pytest tests/test_quiz_tool.py -v
"""
import pytest
from tools.lesson_generator import manage_curriculum
from tools.quiz_tool import manage_quiz


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def setup_lesson(override_db) -> int:
    """Returns a lesson_id in a fresh course/module."""
    course = manage_curriculum(
        action="create_course",
        title="Quiz Course",
        topic="Testing",
        level="intermediate",
        goal="Test quiz functionality",
        hours_per_week=4,
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
        title="Quiz Lesson",
        order_index=0,
        content="Content about Python lists.",
    )
    return lesson["id"]


SINGLE_QUESTIONS = [
    {
        "question": "What does `len([1,2,3])` return?",
        "options": ["3", "2", "1", "0"],
        "correct_answer": "3",
        "type": "single",
    },
    {
        "question": "Which keyword defines a function?",
        "options": ["def", "func", "define", "fn"],
        "correct_answer": "def",
        "type": "single",
    },
]

MULTI_QUESTIONS = [
    {
        "question": "Which are Python data types?",
        "options": ["list", "vector", "dict", "table"],
        "correct_answers": ["list", "dict"],
        "type": "multi",
    }
]

MIXED_QUESTIONS = SINGLE_QUESTIONS + MULTI_QUESTIONS


# ---------------------------------------------------------------------------
# Tests: create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_creates_attempt_with_default_max_score(self, override_db):
        lesson_id = setup_lesson(override_db)
        result = manage_quiz(action="create", lesson_id=lesson_id, questions=SINGLE_QUESTIONS)

        assert "id" in result
        assert result["lesson_id"] == lesson_id
        assert result["max_score"] == 20.0  # 10 * 2 questions
        assert result["is_submitted"] is False

    def test_creates_with_custom_max_score(self, override_db):
        lesson_id = setup_lesson(override_db)
        result = manage_quiz(
            action="create", lesson_id=lesson_id, questions=SINGLE_QUESTIONS, max_score=100.0
        )
        assert result["max_score"] == 100.0

    def test_empty_questions_raises(self, override_db):
        lesson_id = setup_lesson(override_db)
        with pytest.raises(ValueError, match="non-empty"):
            manage_quiz(action="create", lesson_id=lesson_id, questions=[])

    def test_invalid_lesson_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_quiz(action="create", lesson_id=9999, questions=SINGLE_QUESTIONS)


# ---------------------------------------------------------------------------
# Tests: submit — single-answer
# ---------------------------------------------------------------------------

class TestSubmitSingle:
    def _create_attempt(self, override_db) -> int:
        lesson_id = setup_lesson(override_db)
        result = manage_quiz(action="create", lesson_id=lesson_id, questions=SINGLE_QUESTIONS)
        return result["id"]

    def test_all_correct(self, override_db):
        attempt_id = self._create_attempt(override_db)
        result = manage_quiz(
            action="submit",
            attempt_id=attempt_id,
            answers=[
                {"question_index": 0, "selected": ["3"]},
                {"question_index": 1, "selected": ["def"]},
            ],
        )
        assert result["score"] == result["max_score"]
        assert result["passed"] is True
        assert result["weak_areas"] == []

    def test_all_wrong(self, override_db):
        attempt_id = self._create_attempt(override_db)
        result = manage_quiz(
            action="submit",
            attempt_id=attempt_id,
            answers=[
                {"question_index": 0, "selected": ["0"]},
                {"question_index": 1, "selected": ["fn"]},
            ],
        )
        assert result["score"] == 0.0
        assert result["passed"] is False
        assert set(result["weak_areas"]) == {0, 1}

    def test_partial_correct_below_threshold(self, override_db):
        attempt_id = self._create_attempt(override_db)
        result = manage_quiz(
            action="submit",
            attempt_id=attempt_id,
            answers=[
                {"question_index": 0, "selected": ["3"]},  # correct
                {"question_index": 1, "selected": ["fn"]},  # wrong
            ],
        )
        # 1/2 = 50%, below 70% threshold
        assert result["passed"] is False
        assert 1 in result["weak_areas"]

    def test_cannot_submit_twice(self, override_db):
        attempt_id = self._create_attempt(override_db)
        answers = [
            {"question_index": 0, "selected": ["3"]},
            {"question_index": 1, "selected": ["def"]},
        ]
        manage_quiz(action="submit", attempt_id=attempt_id, answers=answers)

        with pytest.raises(ValueError, match="already been submitted"):
            manage_quiz(action="submit", attempt_id=attempt_id, answers=answers)

    def test_case_insensitive_matching(self, override_db):
        lesson_id = setup_lesson(override_db)
        attempt = manage_quiz(
            action="create",
            lesson_id=lesson_id,
            questions=[{
                "question": "Say hello",
                "options": ["Hello", "Bye"],
                "correct_answer": "Hello",
                "type": "single",
            }],
        )
        result = manage_quiz(
            action="submit",
            attempt_id=attempt["id"],
            answers=[{"question_index": 0, "selected": ["hello"]}],  # lowercase
        )
        assert result["score"] > 0


# ---------------------------------------------------------------------------
# Tests: submit — multi-select
# ---------------------------------------------------------------------------

class TestSubmitMulti:
    def _create_attempt(self, override_db) -> int:
        lesson_id = setup_lesson(override_db)
        result = manage_quiz(action="create", lesson_id=lesson_id, questions=MULTI_QUESTIONS)
        return result["id"]

    def test_exact_match_scores_full(self, override_db):
        attempt_id = self._create_attempt(override_db)
        result = manage_quiz(
            action="submit",
            attempt_id=attempt_id,
            answers=[{"question_index": 0, "selected": ["list", "dict"]}],
        )
        assert result["score"] == result["max_score"]
        assert result["passed"] is True

    def test_partial_multi_answer_scores_zero(self, override_db):
        attempt_id = self._create_attempt(override_db)
        result = manage_quiz(
            action="submit",
            attempt_id=attempt_id,
            answers=[{"question_index": 0, "selected": ["list"]}],  # missing "dict"
        )
        assert result["score"] == 0.0

    def test_wrong_multi_answer_scores_zero(self, override_db):
        attempt_id = self._create_attempt(override_db)
        result = manage_quiz(
            action="submit",
            attempt_id=attempt_id,
            answers=[{"question_index": 0, "selected": ["vector", "table"]}],
        )
        assert result["score"] == 0.0


# ---------------------------------------------------------------------------
# Tests: get
# ---------------------------------------------------------------------------

class TestGet:
    def test_get_unsubmitted_attempt(self, override_db):
        lesson_id = setup_lesson(override_db)
        attempt = manage_quiz(action="create", lesson_id=lesson_id, questions=SINGLE_QUESTIONS)
        result = manage_quiz(action="get", attempt_id=attempt["id"])

        assert result["id"] == attempt["id"]
        assert len(result["questions"]) == 2
        assert result["is_submitted"] is False

    def test_get_invalid_raises(self, override_db):
        with pytest.raises(ValueError, match="not found"):
            manage_quiz(action="get", attempt_id=9999)


# ---------------------------------------------------------------------------
# Tests: list
# ---------------------------------------------------------------------------

class TestList:
    def test_lists_attempts_for_lesson(self, override_db):
        lesson_id = setup_lesson(override_db)
        manage_quiz(action="create", lesson_id=lesson_id, questions=SINGLE_QUESTIONS)
        manage_quiz(action="create", lesson_id=lesson_id, questions=MULTI_QUESTIONS)

        result = manage_quiz(action="list", lesson_id=lesson_id)
        assert result["total"] == 2

    def test_empty_lesson_returns_zero(self, override_db):
        lesson_id = setup_lesson(override_db)
        result = manage_quiz(action="list", lesson_id=lesson_id)
        assert result["total"] == 0


# ---------------------------------------------------------------------------
# Tests: results
# ---------------------------------------------------------------------------

class TestResults:
    def test_results_after_submission(self, override_db):
        lesson_id = setup_lesson(override_db)
        attempt = manage_quiz(action="create", lesson_id=lesson_id, questions=SINGLE_QUESTIONS)

        manage_quiz(
            action="submit",
            attempt_id=attempt["id"],
            answers=[
                {"question_index": 0, "selected": ["3"]},   # correct
                {"question_index": 1, "selected": ["fn"]},   # wrong
            ],
        )

        result = manage_quiz(action="results", attempt_id=attempt["id"])
        assert result["percentage"] == 50.0
        assert len(result["questions"]) == 2
        assert result["questions"][0]["is_correct"] is True
        assert result["questions"][1]["is_correct"] is False

    def test_results_before_submission_raises(self, override_db):
        lesson_id = setup_lesson(override_db)
        attempt = manage_quiz(action="create", lesson_id=lesson_id, questions=SINGLE_QUESTIONS)

        with pytest.raises(ValueError, match="not been submitted"):
            manage_quiz(action="results", attempt_id=attempt["id"])


# ---------------------------------------------------------------------------
# Tests: unknown action
# ---------------------------------------------------------------------------

def test_unknown_action_raises(override_db):
    with pytest.raises(ValueError, match="Unknown action"):
        manage_quiz(action="teleport")
