"""Flashcard management tool.

Flashcards are linked to individual lessons and stored in the database.
They are NOT synced to Notion. The agent is responsible for generating
the front/back content; this tool only stores and retrieves it.

Typical workflow:
    1. Agent creates a lesson via manage_curriculum(action="add_lesson", ...)
    2. Agent generates flashcard pairs for that lesson
    3. Agent calls manage_flashcards(action="create", lesson_id=..., cards=[...])
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select

from database import get_db
from models import Course, Flashcard, Lesson, Module


def _fc_to_dict(fc: Flashcard) -> dict:
    return {
        "id": fc.id,
        "lesson_id": fc.lesson_id,
        "front": fc.front,
        "back": fc.back,
        "tags": fc.tags or [],
        "created_at": fc.created_at.isoformat(),
    }


def manage_flashcards(action: str, **kwargs: Any) -> dict:
    """Create, retrieve, or delete flashcards for lessons.

    Actions
    -------
    create
        Required: user_id (str), lesson_id (int),
                  cards (list[dict]) — each dict must have "front" and "back" (str).
                                       Optional "tags" (list[str]) per card.
        Returns:  {"flashcards": [...], "created": <count>}

    list
        Required: lesson_id (int) OR course_id (int) — at least one must be provided.
        Optional: user_id (str) — filter to cards belonging to this user's courses.
                  tags (list[str]) — filter by tag (card must have ALL listed tags)
        Returns:  {"flashcards": [...], "total": <count>}

    get
        Required: flashcard_id (int)
        Returns:  single flashcard dict

    delete
        Required: lesson_id (int) OR flashcard_id (int) — at least one must be provided.
                  If lesson_id is given, all cards for that lesson are deleted.
                  If flashcard_id is given, only that card is deleted.
        Returns:  {"deleted": <count>}
    """
    action = action.strip().lower()

    if action == "create":
        return _create(**kwargs)
    elif action == "list":
        return _list(**kwargs)
    elif action == "get":
        return _get(**kwargs)
    elif action == "delete":
        return _delete(**kwargs)
    else:
        raise ValueError(
            f"Unknown action '{action}'. Valid actions: create, list, get, delete"
        )


def _create(user_id: str, lesson_id: int, cards: list, **_: Any) -> dict:
    if not user_id:
        raise ValueError("'user_id' is required")
    if not cards:
        raise ValueError("'cards' must be a non-empty list")

    with get_db() as db:
        lesson = db.get(Lesson, int(lesson_id))
        if not lesson:
            raise ValueError(f"Lesson {lesson_id} not found")
        module = db.get(Module, lesson.module_id)
        course = db.get(Course, module.course_id) if module else None
        if not course or course.user_id != user_id:
            raise ValueError(f"Lesson {lesson_id} not found")

        created = []
        for card in cards:
            if "front" not in card or "back" not in card:
                raise ValueError("Each card must have 'front' and 'back' keys")
            fc = Flashcard(
                lesson_id=int(lesson_id),
                front=str(card["front"]),
                back=str(card["back"]),
                tags=card.get("tags") or [],
            )
            db.add(fc)
            db.flush()
            created.append(_fc_to_dict(fc))

    return {"flashcards": created, "created": len(created)}


def _list(
    lesson_id: Optional[int] = None,
    course_id: Optional[int] = None,
    user_id: Optional[str] = None,
    tags: Optional[list] = None,
    **_: Any,
) -> dict:
    if lesson_id is None and course_id is None:
        raise ValueError("Provide at least one of: lesson_id, course_id")

    with get_db() as db:
        stmt = (
            select(Flashcard)
            .join(Lesson, Flashcard.lesson_id == Lesson.id)
            .join(Module, Lesson.module_id == Module.id)
            .join(Course, Module.course_id == Course.id)
        )
        if lesson_id is not None:
            stmt = stmt.where(Flashcard.lesson_id == int(lesson_id))
        else:
            stmt = stmt.where(Module.course_id == int(course_id))
        if user_id:
            stmt = stmt.where(Course.user_id == user_id)

        flashcards = db.scalars(stmt).all()
        results = [_fc_to_dict(fc) for fc in flashcards]

        if tags:
            tag_set = {t.lower() for t in tags}
            results = [
                r for r in results
                if tag_set.issubset({t.lower() for t in r["tags"]})
            ]

    return {"flashcards": results, "total": len(results)}


def _get(flashcard_id: int, **_: Any) -> dict:
    with get_db() as db:
        fc = db.get(Flashcard, int(flashcard_id))
        if not fc:
            raise ValueError(f"Flashcard {flashcard_id} not found")
        result = _fc_to_dict(fc)
    return result


def _delete(
    lesson_id: Optional[int] = None,
    flashcard_id: Optional[int] = None,
    **_: Any,
) -> dict:
    if lesson_id is None and flashcard_id is None:
        raise ValueError("Provide at least one of: lesson_id, flashcard_id")

    with get_db() as db:
        if flashcard_id is not None:
            fc = db.get(Flashcard, int(flashcard_id))
            if not fc:
                raise ValueError(f"Flashcard {flashcard_id} not found")
            db.delete(fc)
            count = 1
        else:
            stmt = select(Flashcard).where(Flashcard.lesson_id == int(lesson_id))
            fcs = db.scalars(stmt).all()
            count = len(fcs)
            for fc in fcs:
                db.delete(fc)

    return {"deleted": count}
