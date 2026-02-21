"""Notion integration tool.

Publishes course content (Courses → Modules → Lessons) to Notion.
The database is ALWAYS the source of truth — Notion is a read-only export.
Flashcards and quiz attempts are NOT synced to Notion.

Requires NOTION_API_KEY and NOTION_ROOT_PAGE_ID in your .env file.

Notion structure created
------------------------
Root page (from .env)
  └── Course page
        ├── Course info (callout block)
        └── Curriculum database
              ├── Module entries (type = Module)
              └── Lesson entries (type = Lesson, linked to module)
"""
from __future__ import annotations

from typing import Any, Optional

from notion_client import Client

from config import settings
from database import get_db
from models import Course, Lesson, Module


# ---------------------------------------------------------------------------
# Notion client (lazy — only instantiated when needed)
# ---------------------------------------------------------------------------

def _get_notion_client() -> Client:
    if not settings.notion_api_key:
        raise RuntimeError(
            "NOTION_API_KEY is not set. Add it to your .env file."
        )
    return Client(auth=settings.notion_api_key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rich_text(text: str) -> list:
    """Notion rich_text block helper."""
    return [{"text": {"content": text[:2000]}}]  # Notion 2000-char limit


def _create_course_page(notion: Client, course: Course) -> str:
    """Create the top-level course page under the root page. Returns page_id."""
    root = settings.notion_root_page_id
    parent = {"page_id": root} if root else {"type": "workspace", "workspace": True}

    page = notion.pages.create(
        parent=parent,
        properties={
            "title": {"title": _rich_text(course.title)}
        },
        children=[
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": _rich_text(
                        f"Topic: {course.topic} | Level: {course.level.value} | "
                        f"Goal: {course.goal}"
                    ),
                    "icon": {"emoji": "📚"},
                },
            }
        ],
    )
    return page["id"]


def _create_curriculum_database(notion: Client, course_page_id: str, title: str) -> str:
    """Create the Notion database for modules/lessons. Returns database_id."""
    db = notion.databases.create(
        parent={"page_id": course_page_id},
        title=_rich_text(f"{title} — Curriculum"),
        properties={
            "Name": {"title": {}},
            "Type": {
                "select": {
                    "options": [
                        {"name": "Module", "color": "blue"},
                        {"name": "Lesson", "color": "green"},
                    ]
                }
            },
            "Module": {"rich_text": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "Not Started", "color": "gray"},
                        {"name": "In Progress", "color": "yellow"},
                        {"name": "Completed", "color": "green"},
                    ]
                }
            },
            "Tags": {"multi_select": {}},
        },
    )
    return db["id"]


def _create_module_entry(notion: Client, database_id: str, module: Module) -> str:
    page = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Name": {"title": _rich_text(module.title)},
            "Type": {"select": {"name": "Module"}},
            "Module": {"rich_text": _rich_text(module.title)},
        },
        children=(
            [{"object": "block", "type": "paragraph",
              "paragraph": {"rich_text": _rich_text(module.description)}}]
            if module.description else []
        ),
    )
    return page["id"]


def _create_lesson_entry(
    notion: Client, database_id: str, lesson: Lesson, module_title: str
) -> str:
    children = []
    if lesson.objective:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(f"Objective: {lesson.objective}"),
                "icon": {"emoji": "🎯"},
            },
        })
    if lesson.content:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text(lesson.content)},
        })

    tag_options = [{"name": t} for t in (lesson.tags or [])]

    page = notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Name": {"title": _rich_text(lesson.title)},
            "Type": {"select": {"name": "Lesson"}},
            "Module": {"rich_text": _rich_text(module_title)},
            "Status": {
                "select": {
                    "name": "Completed" if lesson.is_completed else "Not Started"
                }
            },
            "Tags": {"multi_select": tag_options},
        },
        children=children,
    )
    return page["id"]


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------

def manage_notion_page(action: str, **kwargs: Any) -> dict:
    """Create, query, update, or delete Notion pages for a course.

    The database is always the source of truth.
    Notion is a one-way export destination only.
    Flashcards are NOT included in Notion exports.

    Actions
    -------
    publish_course
        Required: course_id (int)
        Creates: Course page → Curriculum database → Module + Lesson entries.
        Updates the DB with Notion IDs for all created pages.
        Returns:  {"course_page_id": ..., "database_id": ..., "pages_created": <n>}

    query_page
        Required: page_id (str)
        Returns:  Notion page metadata dict

    update_page
        Required: page_id (str),
                  properties (dict) — Notion properties object
        Returns:  updated Notion page metadata

    delete_page
        Required: page_id (str)
        Archives the page in Notion (Notion does not support hard delete via API).
        Returns:  {"archived": true, "page_id": ...}

    sync_status
        Required: course_id (int)
        Returns:  {"synced": [...lesson dicts...], "unsynced": [...lesson dicts...],
                   "last_synced_at": ...}
    """
    action = action.strip().lower()

    if action == "publish_course":
        return _publish_course(**kwargs)
    elif action == "query_page":
        return _query_page(**kwargs)
    elif action == "update_page":
        return _update_page(**kwargs)
    elif action == "delete_page":
        return _delete_page(**kwargs)
    elif action == "sync_status":
        return _sync_status(**kwargs)
    else:
        raise ValueError(
            f"Unknown action '{action}'. Valid actions: publish_course, query_page, "
            "update_page, delete_page, sync_status"
        )


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

def _publish_course(course_id: int, **_: Any) -> dict:
    notion = _get_notion_client()

    with get_db() as db:
        course = db.get(Course, int(course_id))
        if not course:
            raise ValueError(f"Course {course_id} not found")

        course_page_id = _create_course_page(notion, course)
        database_id = _create_curriculum_database(notion, course_page_id, course.title)

        pages_created = 0
        for module in course.modules:
            mod_page_id = _create_module_entry(notion, database_id, module)
            module.notion_page_id = mod_page_id
            pages_created += 1

            for lesson in module.lessons:
                lesson_page_id = _create_lesson_entry(
                    notion, database_id, lesson, module.title
                )
                lesson.notion_page_id = lesson_page_id
                pages_created += 1

        from datetime import datetime
        course.notion_page_id = course_page_id
        course.notion_database_id = database_id
        course.last_synced_at = datetime.utcnow()
        db.flush()

    return {
        "course_page_id": course_page_id,
        "database_id": database_id,
        "pages_created": pages_created,
    }


def _query_page(page_id: str, **_: Any) -> dict:
    notion = _get_notion_client()
    return notion.pages.retrieve(page_id=page_id)


def _update_page(page_id: str, properties: dict, **_: Any) -> dict:
    notion = _get_notion_client()
    return notion.pages.update(page_id=page_id, properties=properties)


def _delete_page(page_id: str, **_: Any) -> dict:
    notion = _get_notion_client()
    notion.pages.update(page_id=page_id, archived=True)
    return {"archived": True, "page_id": page_id}


def _sync_status(course_id: int, **_: Any) -> dict:
    with get_db() as db:
        course = db.get(Course, int(course_id))
        if not course:
            raise ValueError(f"Course {course_id} not found")

        synced = []
        unsynced = []

        for module in course.modules:
            for lesson in module.lessons:
                entry = {
                    "lesson_id": lesson.id,
                    "lesson_title": lesson.title,
                    "module_title": module.title,
                    "notion_page_id": lesson.notion_page_id,
                }
                if lesson.notion_page_id:
                    synced.append(entry)
                else:
                    unsynced.append(entry)

    return {
        "synced": synced,
        "unsynced": unsynced,
        "last_synced_at": course.last_synced_at.isoformat() if course.last_synced_at else None,
    }
