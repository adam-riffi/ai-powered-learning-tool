"""Agent tools package.

Exports four tool functions and TOOL_SCHEMAS — ready to pass to
`anthropic.Anthropic().messages.create(tools=TOOL_SCHEMAS, ...)`.

Quick import
------------
    from tools import manage_curriculum, manage_flashcards, manage_quiz, manage_notion_page
    from tools import TOOL_SCHEMAS
"""
from tools.lesson_generator import manage_curriculum
from tools.flashcard_tool import manage_flashcards
from tools.quiz_tool import manage_quiz
from tools.notion_tool import manage_notion_page

__all__ = [
    "manage_curriculum",
    "manage_flashcards",
    "manage_quiz",
    "manage_notion_page",
    "TOOL_SCHEMAS",
]

# ---------------------------------------------------------------------------
# Anthropic-compatible tool schemas
# Pass these directly to client.messages.create(tools=TOOL_SCHEMAS)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "manage_curriculum",
        "description": (
            "Manage the learning curriculum database. "
            "Create courses, add modules and lessons, update lesson content, "
            "search lessons, and delete courses. "
            "Use this tool to build and maintain the full learning structure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create_course", "add_module", "add_lesson",
                        "update_lesson", "get_course", "list_courses",
                        "delete_course", "search_lessons"
                    ],
                    "description": "The operation to perform.",
                },
                "title": {"type": "string", "description": "Course or lesson title."},
                "topic": {"type": "string", "description": "Course topic (create_course only)."},
                "level": {
                    "type": "string",
                    "enum": ["beginner", "intermediate", "advanced"],
                    "description": "Difficulty level (create_course only).",
                },
                "goal": {"type": "string", "description": "Learning goal (create_course only)."},
                "hours_per_week": {
                    "type": "integer",
                    "description": "Estimated study hours per week (create_course only).",
                },
                "course_id": {"type": "integer", "description": "Course ID."},
                "module_id": {"type": "integer", "description": "Module ID."},
                "lesson_id": {"type": "integer", "description": "Lesson ID."},
                "order_index": {"type": "integer", "description": "Position within parent (0-based)."},
                "description": {"type": "string", "description": "Module description."},
                "objective": {"type": "string", "description": "Lesson learning objective."},
                "content": {"type": "string", "description": "Lesson content in markdown."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topic tags for filtering.",
                },
                "is_completed": {"type": "boolean", "description": "Mark lesson completed."},
                "query": {"type": "string", "description": "Search term (search_lessons only)."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "manage_flashcards",
        "description": (
            "Create, list, retrieve, or delete flashcards for lessons. "
            "Flashcards are stored in the database and not synced to Notion. "
            "Always create flashcards immediately after adding a lesson."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "get", "delete"],
                    "description": "The operation to perform.",
                },
                "lesson_id": {"type": "integer", "description": "Lesson ID."},
                "course_id": {"type": "integer", "description": "Course ID (for list by course)."},
                "flashcard_id": {"type": "integer", "description": "Flashcard ID (for get/delete)."},
                "cards": {
                    "type": "array",
                    "description": "List of flashcard objects for create action.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "front": {"type": "string", "description": "Question or term."},
                            "back": {"type": "string", "description": "Answer or definition."},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional topic tags.",
                            },
                        },
                        "required": ["front", "back"],
                    },
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags (list action only).",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "manage_quiz",
        "description": (
            "Create quiz attempts, submit answers, and retrieve results for lessons. "
            "Supports single-answer (radio) and multi-select (checkbox) questions. "
            "No open-ended questions. Scoring is automatic."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "submit", "get", "list", "results"],
                    "description": "The operation to perform.",
                },
                "lesson_id": {"type": "integer", "description": "Lesson ID."},
                "attempt_id": {"type": "integer", "description": "Quiz attempt ID."},
                "max_score": {
                    "type": "number",
                    "description": "Total possible score (defaults to 10 × num_questions).",
                },
                "questions": {
                    "type": "array",
                    "description": "List of question objects (create action).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "correct_answer": {
                                "type": "string",
                                "description": "Single correct option (type=single).",
                            },
                            "correct_answers": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Multiple correct options (type=multi).",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["single", "multi"],
                                "description": "Question type. Defaults to 'single'.",
                            },
                        },
                        "required": ["question", "options"],
                    },
                },
                "answers": {
                    "type": "array",
                    "description": "List of answer objects (submit action).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_index": {"type": "integer"},
                            "selected": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Always a list, even for single-answer.",
                            },
                        },
                        "required": ["question_index", "selected"],
                    },
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "manage_notion_page",
        "description": (
            "Publish course content to Notion or manage existing Notion pages. "
            "The database is always the source of truth — Notion is export-only. "
            "Flashcards are never included in Notion exports. "
            "Requires NOTION_API_KEY and NOTION_ROOT_PAGE_ID in .env."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "publish_course", "query_page",
                        "update_page", "delete_page", "sync_status"
                    ],
                    "description": "The operation to perform.",
                },
                "course_id": {
                    "type": "integer",
                    "description": "Course ID (publish_course and sync_status).",
                },
                "page_id": {
                    "type": "string",
                    "description": "Notion page ID (query_page, update_page, delete_page).",
                },
                "properties": {
                    "type": "object",
                    "description": "Notion properties object for update_page.",
                },
            },
            "required": ["action"],
        },
    },
]
