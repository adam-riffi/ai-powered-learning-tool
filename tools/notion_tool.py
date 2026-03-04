"""Notion integration tool.

Publishes course content (Courses -> Modules -> Lessons) to Notion.
The database is always the source of truth — Notion is a one-way export.
Flashcards and quiz attempts are not synced to Notion.

Requires NOTION_API_KEY and NOTION_ROOT_PAGE_ID in .env,
or pass api_key/root_page_id directly to publish_course for session-based auth.

Notion structure created on publish:
    Root page
      Course page
        Course info callout
        Curriculum database
          Module entries  (Type = Module)
          Lesson entries  (Type = Lesson, linked to module by name)
"""
from __future__ import annotations

import json
import re
import time as _time
from datetime import datetime
from typing import Any, Optional

from notion_client import Client

from config import settings
from database import get_db
from models import Course, Lesson, Module


def _get_notion_client(api_key: Optional[str] = None) -> Client:
    key = api_key or settings.notion_api_key
    if not key:
        raise RuntimeError(
            "NOTION_API_KEY is not set. Add it to your .env file or connect via the Notion page."
        )
    return Client(auth=key)


def _rich_text(text: str) -> list:
    """Return Notion rich_text format. Splits text longer than 2000 chars into multiple annotations."""
    text = str(text)
    if len(text) <= 2000:
        return [{"text": {"content": text}}]
    return [{"text": {"content": text[i:i + 2000]}} for i in range(0, len(text), 2000)]


def _archive_page_if_exists(notion: Client, page_id: Optional[str]) -> None:
    if not page_id:
        return
    try:
        notion.pages.update(page_id=page_id, archived=True)
    except Exception:
        pass


def _clean_lesson_content(text: str) -> str:
    """Strip JSON wrapper artefacts from lesson content."""
    if not text:
        return text

    stripped = text.strip()

    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "content" in data:
                return _clean_lesson_content(str(data["content"]))
        except (json.JSONDecodeError, ValueError):
            pass

        match = re.search(r'(#{1,3}\s+\S)', stripped)
        if match:
            return stripped[match.start():].strip()

        match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', stripped)
        if match:
            try:
                inner = json.loads('"' + match.group(1) + '"')
                return _clean_lesson_content(inner)
            except (json.JSONDecodeError, ValueError):
                pass

        match = re.search(r'"content"\s*:\s*"(.+)', stripped, re.DOTALL)
        if match:
            raw_after = match.group(1)
            md_match = re.search(r'(#{1,3}\s+\S)', raw_after)
            if md_match:
                return raw_after[md_match.start():].strip().rstrip('"}').strip()

    lines = stripped.split("\n")
    clean_lines = []
    skip_json_header = False

    for line in lines:
        s = line.strip()

        if s == "{":
            skip_json_header = True
            continue

        if skip_json_header and s.startswith('"content"'):
            skip_json_header = False
            m = re.search(r'"content"\s*:\s*"(.*)', s)
            if m:
                partial = m.group(1).rstrip('"').strip()
                if partial:
                    clean_lines.append(partial)
            continue

        if skip_json_header:
            continue

        if s.startswith('{"title"') or s.startswith('{"objective"') or s.startswith('{"content"'):
            m = re.search(r'"content"\s*:\s*"(.+)', s)
            if m:
                partial = m.group(1).rstrip('"').rstrip('}').strip()
                if partial:
                    clean_lines.append(partial)
            continue

        if re.match(r'^\s*"(title|objective)"\s*:', s):
            continue

        clean_lines.append(line)

    result = "\n".join(clean_lines).strip()
    result = result.rstrip('"}').strip()
    return result


def _append_blocks_in_batches(notion: Client, page_id: str, blocks: list) -> None:
    """Send blocks to Notion in batches of 20 with retry and rate-limit sleep."""
    batch_size = 20
    sleep_between = 0.4
    max_retries = 3

    for i in range(0, len(blocks), batch_size):
        batch = blocks[i:i + batch_size]
        for attempt in range(max_retries):
            try:
                notion.blocks.children.append(block_id=page_id, children=batch)
                break
            except Exception as e:
                err = str(e).lower()
                if attempt < max_retries - 1 and ("429" in err or "rate" in err or "timeout" in err):
                    _time.sleep(2 ** attempt)
                else:
                    raise
        _time.sleep(sleep_between)


def _paragraph_blocks(text: str) -> list:
    """Create one or more paragraph blocks, splitting at sentence boundaries."""
    if not text:
        return []
    blocks = []
    while len(text) > 1900:
        cut = text.rfind('. ', 0, 1900)
        if cut == -1:
            cut = text.rfind(' ', 0, 1900)
        if cut == -1:
            cut = 1900
        else:
            cut += 1
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": text[:cut].strip()}}]},
        })
        text = text[cut:].strip()
    if text:
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": text}}]},
        })
    return blocks


def _markdown_to_blocks(text: str) -> list:
    """Convert simple markdown to Notion block objects.

    Handles: headings (#-####), bullet lists (- *), numbered lists,
    blockquotes (>), code fences, paragraphs.
    Long paragraphs are split to respect the 2000-char annotation limit.
    """
    blocks = []
    lines = text.split("\n")
    in_code_block = False
    code_lines: list[str] = []
    code_lang = ""

    for line in lines:
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = line.strip()[3:].strip() or "plain text"
                code_lines = []
            else:
                in_code_block = False
                code_content = "\n".join(code_lines)
                if code_content:
                    blocks.append({
                        "object": "block",
                        "type": "code",
                        "code": {
                            "rich_text": [{"text": {"content": code_content[:2000]}}],
                            "language": code_lang if code_lang in [
                                "python", "javascript", "typescript", "java", "c", "cpp",
                                "css", "html", "bash", "json", "sql", "markdown",
                            ] else "plain text",
                        },
                    })
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        s = line.strip()
        if not s:
            continue

        if s.startswith("#### "):
            blocks.append({"object": "block", "type": "heading_3",
                            "heading_3": {"rich_text": [{"text": {"content": s[5:][:2000]}}]}})
        elif s.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                            "heading_3": {"rich_text": [{"text": {"content": s[4:][:2000]}}]}})
        elif s.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                            "heading_2": {"rich_text": [{"text": {"content": s[3:][:2000]}}]}})
        elif s.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1",
                            "heading_1": {"rich_text": [{"text": {"content": s[2:][:2000]}}]}})
        elif s.startswith("- ") or s.startswith("* "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                            "bulleted_list_item": {"rich_text": [{"text": {"content": s[2:][:2000]}}]}})
        elif len(s) > 2 and s[0].isdigit() and s[1] in ".)" and s[2] == " ":
            blocks.append({"object": "block", "type": "numbered_list_item",
                            "numbered_list_item": {"rich_text": [{"text": {"content": s[3:][:2000]}}]}})
        elif s.startswith("> "):
            blocks.append({"object": "block", "type": "quote",
                            "quote": {"rich_text": [{"text": {"content": s[2:][:2000]}}]}})
        else:
            blocks.extend(_paragraph_blocks(s))

    return blocks


def _create_course_page(notion: Client, course: Course, root_page_id: Optional[str] = None) -> str:
    root = root_page_id or settings.notion_root_page_id
    parent = {"type": "page_id", "page_id": root} if root else {"type": "workspace", "workspace": True}

    page = notion.pages.create(
        parent=parent,
        properties={"title": {"title": _rich_text(course.title)}},
        children=[
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": _rich_text(
                        f"Level: {course.level.value}  |  "
                        f"Goal: {course.goal}  |  "
                        f"Topic: {course.topic}"
                    ),
                    "color": "blue_background",
                },
            }
        ],
    )
    return page["id"]


def _create_curriculum_database(notion: Client, course_page_id: str, title: str) -> str:
    db = notion.databases.create(
        parent={"type": "page_id", "page_id": course_page_id},
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


def _get_database_properties(notion: Client, database_id: str) -> set:
    db = notion.databases.retrieve(database_id=database_id)
    return set(db.get("properties", {}).keys())


def _create_module_entry(notion: Client, database_id: str, module: Module) -> str:
    existing_props = _get_database_properties(notion, database_id)

    properties: dict = {"Name": {"title": _rich_text(module.title)}}
    if "Type" in existing_props:
        properties["Type"] = {"select": {"name": "Module"}}
    if "Module" in existing_props:
        properties["Module"] = {"rich_text": _rich_text(module.title)}

    children = []
    if module.description:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(module.description),
                "color": "blue_background",
            },
        })

    page = notion.pages.create(
        parent={"type": "database_id", "database_id": database_id},
        properties=properties,
        children=children,
    )
    return page["id"]


def _create_lesson_entry(notion: Client, database_id: str, lesson: Lesson, module_title: str) -> str:
    existing_props = _get_database_properties(notion, database_id)

    children = []

    if lesson.objective:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(f"Objective: {lesson.objective}"),
                "color": "green_background",
            },
        })

    if lesson.objective and lesson.content:
        children.append({"object": "block", "type": "divider", "divider": {}})

    if lesson.content:
        raw = lesson.content.replace('\\n', '\n').replace('\\t', '\t')
        clean_content = _clean_lesson_content(raw)
        children.extend(_markdown_to_blocks(clean_content))

    properties: dict = {"Name": {"title": _rich_text(lesson.title)}}
    if "Type" in existing_props:
        properties["Type"] = {"select": {"name": "Lesson"}}
    if "Module" in existing_props:
        properties["Module"] = {"rich_text": _rich_text(module_title)}
    if "Status" in existing_props:
        properties["Status"] = {
            "select": {"name": "Completed" if lesson.is_completed else "Not Started"}
        }
    if "Tags" in existing_props:
        properties["Tags"] = {"multi_select": [{"name": t} for t in (lesson.tags or [])]}

    first_batch = children[:20]
    rest = children[20:]

    page = notion.pages.create(
        parent={"type": "database_id", "database_id": database_id},
        properties=properties,
        children=first_batch,
    )
    page_id = page["id"]

    if rest:
        _time.sleep(0.5)
        _append_blocks_in_batches(notion, page_id, rest)

    return page_id


def _publish_course(
    course_id: int,
    api_key: Optional[str] = None,
    root_page_id: Optional[str] = None,
    **_: Any,
) -> dict:
    notion = _get_notion_client(api_key=api_key)

    with get_db() as db:
        course = db.get(Course, int(course_id))
        if not course:
            raise ValueError(f"Course {course_id} not found")

        old_course_page_id = course.notion_page_id

        course_page_id = _create_course_page(notion, course, root_page_id=root_page_id)
        database_id = _create_curriculum_database(notion, course_page_id, course.title)

        pages_created = 0
        for module in course.modules:
            mod_page_id = _create_module_entry(notion, database_id, module)
            module.notion_page_id = mod_page_id
            pages_created += 1

            for lesson in module.lessons:
                lesson_page_id = _create_lesson_entry(notion, database_id, lesson, module.title)
                lesson.notion_page_id = lesson_page_id
                pages_created += 1

        course.notion_page_id = course_page_id
        course.notion_database_id = database_id
        course.last_synced_at = datetime.utcnow()
        db.flush()

        _archive_page_if_exists(notion, old_course_page_id)

    return {
        "course_page_id": course_page_id,
        "database_id": database_id,
        "pages_created": pages_created,
    }


def _query_page(page_id: str, api_key: Optional[str] = None, **_: Any) -> dict:
    notion = _get_notion_client(api_key=api_key)
    return notion.pages.retrieve(page_id=page_id)


def _update_page(page_id: str, properties: dict, api_key: Optional[str] = None, **_: Any) -> dict:
    notion = _get_notion_client(api_key=api_key)
    return notion.pages.update(page_id=page_id, properties=properties)


def _delete_page(page_id: str, api_key: Optional[str] = None, **_: Any) -> dict:
    notion = _get_notion_client(api_key=api_key)
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
                (synced if lesson.notion_page_id else unsynced).append(entry)

    return {
        "synced": synced,
        "unsynced": unsynced,
        "last_synced_at": course.last_synced_at.isoformat() if course.last_synced_at else None,
    }


def manage_notion_page(action: str, **kwargs: Any) -> dict:
    """Create, query, update, or delete Notion pages for a course.

    Actions: publish_course / query_page / update_page / delete_page / sync_status

    Optional kwargs for session-based auth (overrides .env):
        api_key      : str  -- Notion integration token
        root_page_id : str  -- Notion root page ID
    """
    action = action.strip().lower()
    dispatch = {
        "publish_course": _publish_course,
        "query_page": _query_page,
        "update_page": _update_page,
        "delete_page": _delete_page,
        "sync_status": _sync_status,
    }
    fn = dispatch.get(action)
    if fn is None:
        raise ValueError(
            f"Unknown action '{action}'. "
            "Valid actions: publish_course, query_page, update_page, delete_page, sync_status"
        )
    return fn(**kwargs)
