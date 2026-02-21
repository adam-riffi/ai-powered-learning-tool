"""Lesson / curriculum management tool.

This tool handles all CRUD operations for the curriculum database:
courses, modules, and lessons. It is the primary tool the agent uses
to build and maintain the learning structure.

All functions are agent-agnostic — no LLM calls here.
The agent is responsible for generating content; this tool stores it.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import or_, select

from database import get_db
from models import Course, CourseLevel, CourseStatus, Lesson, Module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _course_to_dict(course: Course) -> dict:
    return {
        "id": course.id,
        "title": course.title,
        "topic": course.topic,
        "level": course.level.value,
        "goal": course.goal,
        "hours_per_week": course.hours_per_week,
        "status": course.status.value,
        "notion_page_id": course.notion_page_id,
        "notion_database_id": course.notion_database_id,
        "last_synced_at": course.last_synced_at.isoformat() if course.last_synced_at else None,
        "created_at": course.created_at.isoformat(),
        "updated_at": course.updated_at.isoformat(),
    }


def _module_to_dict(module: Module) -> dict:
    return {
        "id": module.id,
        "course_id": module.course_id,
        "title": module.title,
        "description": module.description,
        "order_index": module.order_index,
        "notion_page_id": module.notion_page_id,
        "created_at": module.created_at.isoformat(),
    }


def _lesson_to_dict(lesson: Lesson, include_flashcards: bool = False) -> dict:
    d = {
        "id": lesson.id,
        "module_id": lesson.module_id,
        "title": lesson.title,
        "objective": lesson.objective,
        "content": lesson.content,
        "tags": lesson.tags or [],
        "order_index": lesson.order_index,
        "is_completed": lesson.is_completed,
        "notion_page_id": lesson.notion_page_id,
        "created_at": lesson.created_at.isoformat(),
        "updated_at": lesson.updated_at.isoformat(),
    }
    if include_flashcards:
        d["flashcards"] = [
            {
                "id": fc.id,
                "front": fc.front,
                "back": fc.back,
                "tags": fc.tags or [],
                "created_at": fc.created_at.isoformat(),
            }
            for fc in lesson.flashcards
        ]
    return d


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------

def manage_curriculum(action: str, **kwargs: Any) -> dict:
    """Manage courses, modules, and lessons in the learning database.

    Actions
    -------
    create_course
        Required: title (str), topic (str), level (str: beginner/intermediate/advanced),
                  goal (str), hours_per_week (int)
        Returns:  course dict

    add_module
        Required: course_id (int), title (str), order_index (int)
        Optional: description (str)
        Returns:  module dict

    add_lesson
        Required: module_id (int), title (str), order_index (int)
        Optional: objective (str), content (str — markdown), tags (list[str])
        Returns:  lesson dict with an empty "flashcards" list
                  (the agent should call manage_flashcards next to populate cards)

    update_lesson
        Required: lesson_id (int)
        Optional: title, objective, content, tags, is_completed — any subset
        Returns:  updated lesson dict

    get_course
        Required: course_id (int)
        Returns:  full tree — course → modules → lessons (with flashcard count)

    list_courses
        No parameters.
        Returns:  list of course summary dicts

    delete_course
        Required: course_id (int)
        Returns:  {"deleted": true, "course_id": <id>}

    search_lessons
        Required: query (str) — matched against title, objective, content, tags
        Optional: course_id (int) — restrict search to a specific course
        Returns:  list of matching lesson dicts (without full content by default)
    """
    action = action.strip().lower()

    if action == "create_course":
        return _create_course(**kwargs)
    elif action == "add_module":
        return _add_module(**kwargs)
    elif action == "add_lesson":
        return _add_lesson(**kwargs)
    elif action == "update_lesson":
        return _update_lesson(**kwargs)
    elif action == "get_course":
        return _get_course(**kwargs)
    elif action == "list_courses":
        return _list_courses()
    elif action == "delete_course":
        return _delete_course(**kwargs)
    elif action == "search_lessons":
        return _search_lessons(**kwargs)
    else:
        raise ValueError(
            f"Unknown action '{action}'. Valid actions: create_course, add_module, "
            "add_lesson, update_lesson, get_course, list_courses, delete_course, search_lessons"
        )


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

def _create_course(
    title: str,
    topic: str,
    level: str,
    goal: str,
    hours_per_week: int,
    **_: Any,
) -> dict:
    try:
        course_level = CourseLevel(level.lower())
    except ValueError:
        raise ValueError(f"Invalid level '{level}'. Must be: beginner, intermediate, advanced")

    with get_db() as db:
        course = Course(
            title=title,
            topic=topic,
            level=course_level,
            goal=goal,
            hours_per_week=int(hours_per_week),
            status=CourseStatus.DRAFT,
        )
        db.add(course)
        db.flush()
        result = _course_to_dict(course)
    return result


def _add_module(
    course_id: int,
    title: str,
    order_index: int,
    description: Optional[str] = None,
    **_: Any,
) -> dict:
    with get_db() as db:
        course = db.get(Course, int(course_id))
        if not course:
            raise ValueError(f"Course {course_id} not found")

        module = Module(
            course_id=int(course_id),
            title=title,
            description=description,
            order_index=int(order_index),
        )
        db.add(module)
        db.flush()
        result = _module_to_dict(module)
    return result


def _add_lesson(
    module_id: int,
    title: str,
    order_index: int,
    objective: Optional[str] = None,
    content: Optional[str] = None,
    tags: Optional[list] = None,
    **_: Any,
) -> dict:
    with get_db() as db:
        module = db.get(Module, int(module_id))
        if not module:
            raise ValueError(f"Module {module_id} not found")

        lesson = Lesson(
            module_id=int(module_id),
            title=title,
            objective=objective,
            content=content,
            tags=tags or [],
            order_index=int(order_index),
            is_completed=False,
        )
        db.add(lesson)
        db.flush()
        result = _lesson_to_dict(lesson, include_flashcards=True)
    return result


def _update_lesson(lesson_id: int, **kwargs: Any) -> dict:
    allowed = {"title", "objective", "content", "tags", "is_completed"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}

    with get_db() as db:
        lesson = db.get(Lesson, int(lesson_id))
        if not lesson:
            raise ValueError(f"Lesson {lesson_id} not found")

        for key, value in updates.items():
            setattr(lesson, key, value)
        db.flush()
        result = _lesson_to_dict(lesson)
    return result


def _get_course(course_id: int, **_: Any) -> dict:
    with get_db() as db:
        course = db.get(Course, int(course_id))
        if not course:
            raise ValueError(f"Course {course_id} not found")

        result = _course_to_dict(course)
        result["modules"] = []

        for module in course.modules:
            mod_dict = _module_to_dict(module)
            mod_dict["lessons"] = []
            for lesson in module.lessons:
                lesson_dict = _lesson_to_dict(lesson)
                lesson_dict["flashcard_count"] = len(lesson.flashcards)
                lesson_dict["quiz_attempt_count"] = len(lesson.quiz_attempts)
                mod_dict["lessons"].append(lesson_dict)
            result["modules"].append(mod_dict)

    return result


def _list_courses(**_: Any) -> dict:
    with get_db() as db:
        courses = db.scalars(select(Course).order_by(Course.created_at.desc())).all()
        result = []
        for course in courses:
            summary = _course_to_dict(course)
            summary["module_count"] = len(course.modules)
            summary["lesson_count"] = sum(len(m.lessons) for m in course.modules)
            result.append(summary)
    return {"courses": result, "total": len(result)}


def _delete_course(course_id: int, **_: Any) -> dict:
    with get_db() as db:
        course = db.get(Course, int(course_id))
        if not course:
            raise ValueError(f"Course {course_id} not found")
        db.delete(course)
    return {"deleted": True, "course_id": int(course_id)}


def _search_lessons(query: str, course_id: Optional[int] = None, **_: Any) -> dict:
    term = f"%{query}%"
    with get_db() as db:
        stmt = (
            select(Lesson)
            .join(Module)
            .where(
                or_(
                    Lesson.title.ilike(term),
                    Lesson.objective.ilike(term),
                    Lesson.content.ilike(term),
                )
            )
        )
        if course_id is not None:
            stmt = stmt.where(Module.course_id == int(course_id))

        lessons = db.scalars(stmt).all()

        results = []
        for lesson in lessons:
            d = _lesson_to_dict(lesson)
            # Truncate content for search results
            if d["content"] and len(d["content"]) > 300:
                d["content"] = d["content"][:300] + "..."
            results.append(d)

    return {"lessons": results, "total": len(results), "query": query}
