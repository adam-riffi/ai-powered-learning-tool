"""Quiz management tool.

Handles storing, retrieving, and scoring quiz attempts for lessons.
No content generation happens here — this module only manages persistence
and scoring logic.

Question types:
    single  — one correct answer (correct_answer: str)
    multi   — multiple correct answers (correct_answers: list[str])

Scoring:
    Each question is worth max_score / num_questions points.
    Multi-select: full credit only if the selected set exactly matches correct_answers.
    Pass threshold: 70%.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from database import get_db
from models import Course, Lesson, Module, QuizAttempt


def _attempt_to_dict(attempt: QuizAttempt, include_questions: bool = True) -> dict:
    d: dict = {
        "id": attempt.id,
        "lesson_id": attempt.lesson_id,
        "score": attempt.score,
        "max_score": attempt.max_score,
        "passed": attempt.passed,
        "weak_areas": attempt.weak_areas or [],
        "created_at": attempt.created_at.isoformat(),
        "completed_at": attempt.completed_at.isoformat() if attempt.completed_at else None,
        "is_submitted": attempt.completed_at is not None,
    }
    if include_questions:
        d["questions"] = attempt.questions or []
        d["answers"] = attempt.answers or []
    return d


def _score_question(question: dict, selected: list) -> bool:
    """Return True if the submitted answer is fully correct."""
    qtype = question.get("type", "single")
    if qtype == "single":
        correct = str(question.get("correct_answer", "")).strip().upper()
        user = str(selected[0]).strip().upper() if selected else ""
        return user == correct
    elif qtype == "multi":
        correct_set = {str(a).strip().upper() for a in question.get("correct_answers", [])}
        user_set = {str(a).strip().upper() for a in selected}
        return user_set == correct_set
    return False


def manage_quiz(action: str, **kwargs: Any) -> dict:
    """Create, submit, and retrieve quiz attempts for lessons.

    Actions:
        create  — store a new set of questions for a lesson
        submit  — score a submitted attempt
        get     — retrieve an attempt with its questions
        list    — list all attempts for a lesson
        results — per-question breakdown after submission
    """
    action = action.strip().lower()

    if action == "create":
        return _create(**kwargs)
    elif action == "submit":
        return _submit(**kwargs)
    elif action == "get":
        return _get(**kwargs)
    elif action == "list":
        return _list(**kwargs)
    elif action == "results":
        return _results(**kwargs)
    else:
        raise ValueError(
            f"Unknown action '{action}'. "
            "Valid actions: create, submit, get, list, results"
        )


def _create(
    lesson_id: int,
    questions: list,
    user_id: Optional[str] = None,
    max_score: Optional[float] = None,
    **_: Any,
) -> dict:
    if not questions:
        raise ValueError("'questions' must be a non-empty list")

    with get_db() as db:
        lesson = db.get(Lesson, int(lesson_id))
        if not lesson:
            raise ValueError(f"Lesson {lesson_id} not found")

        if user_id:
            module = db.get(Module, lesson.module_id)
            course = db.get(Course, module.course_id) if module else None
            if not course or course.user_id != user_id:
                raise ValueError(f"Lesson {lesson_id} not found")

        score_total = float(max_score) if max_score is not None else float(10 * len(questions))

        attempt = QuizAttempt(
            lesson_id=int(lesson_id),
            questions=questions,
            max_score=score_total,
        )
        db.add(attempt)
        db.flush()
        result = _attempt_to_dict(attempt)

    return result


def _submit(attempt_id: int, answers: list, **_: Any) -> dict:
    with get_db() as db:
        attempt = db.get(QuizAttempt, int(attempt_id))
        if not attempt:
            raise ValueError(f"Quiz attempt {attempt_id} not found")
        if attempt.completed_at is not None:
            raise ValueError("This quiz has already been submitted")

        questions = attempt.questions
        points_per_q = attempt.max_score / len(questions) if questions else 0.0

        answer_map: dict[int, list] = {
            int(a["question_index"]): a.get("selected", [])
            for a in answers
        }

        score = 0.0
        weak_areas: list[int] = []

        for idx, question in enumerate(questions):
            selected = answer_map.get(idx, [])
            if _score_question(question, selected):
                score += points_per_q
            else:
                weak_areas.append(idx)

        passed = (score / attempt.max_score) >= 0.7 if attempt.max_score > 0 else False

        attempt.answers = answers
        attempt.score = round(score, 2)
        attempt.passed = passed
        attempt.weak_areas = weak_areas
        attempt.completed_at = datetime.now(timezone.utc)
        db.flush()

        result = _attempt_to_dict(attempt)

    return result


def _get(attempt_id: int, **_: Any) -> dict:
    with get_db() as db:
        attempt = db.get(QuizAttempt, int(attempt_id))
        if not attempt:
            raise ValueError(f"Quiz attempt {attempt_id} not found")
        result = _attempt_to_dict(attempt, include_questions=True)
    return result


def _list(lesson_id: int, user_id: Optional[str] = None, **_: Any) -> dict:
    with get_db() as db:
        stmt = (
            select(QuizAttempt)
            .join(Lesson, QuizAttempt.lesson_id == Lesson.id)
            .join(Module, Lesson.module_id == Module.id)
            .join(Course, Module.course_id == Course.id)
            .where(QuizAttempt.lesson_id == int(lesson_id))
            .order_by(QuizAttempt.created_at.desc())
        )

        if user_id:
            stmt = stmt.where(Course.user_id == user_id)

        attempts = db.scalars(stmt).all()
        results = [_attempt_to_dict(a, include_questions=False) for a in attempts]

    return {"attempts": results, "total": len(results)}


def _results(attempt_id: int, **_: Any) -> dict:
    with get_db() as db:
        attempt = db.get(QuizAttempt, int(attempt_id))
        if not attempt:
            raise ValueError(f"Quiz attempt {attempt_id} not found")
        if not attempt.completed_at:
            raise ValueError("This quiz has not been submitted yet")

        questions = attempt.questions
        answer_map: dict[int, list] = {
            int(a["question_index"]): a.get("selected", [])
            for a in (attempt.answers or [])
        }

        breakdown = []
        for idx, question in enumerate(questions):
            selected = answer_map.get(idx, [])
            is_correct = _score_question(question, selected)
            qtype = question.get("type", "single")
            correct_display = (
                question.get("correct_answer")
                if qtype == "single"
                else question.get("correct_answers", [])
            )
            breakdown.append({
                "question_index": idx,
                "question": question.get("question"),
                "options": question.get("options", []),
                "type": qtype,
                "user_answer": selected,
                "correct_answer": correct_display,
                "is_correct": is_correct,
            })

        pct = round(attempt.score / attempt.max_score * 100, 1) if attempt.max_score else 0

        return {
            "attempt_id": attempt_id,
            "lesson_id": attempt.lesson_id,
            "score": attempt.score,
            "max_score": attempt.max_score,
            "percentage": pct,
            "passed": attempt.passed,
            "weak_areas": attempt.weak_areas or [],
            "questions": breakdown,
        }
