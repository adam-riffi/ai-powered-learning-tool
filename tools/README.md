# Tools Package

The four tools your agent calls. Each tool is a single Python function that accepts
plain arguments and returns a plain `dict`. No LLM calls, no async, no side effects
outside the database (and Notion for `notion_tool`).

---

## Quick reference

| Tool function | File | Purpose |
|---|---|---|
| `manage_curriculum` | `lesson_generator.py` | CRUD for courses, modules, lessons |
| `manage_flashcards` | `flashcard_tool.py` | CRUD for flashcards |
| `manage_quiz` | `quiz_tool.py` | Create and score quiz attempts |
| `manage_notion_page` | `notion_tool.py` | Publish and manage Notion pages |

All tools are re-exported from `tools/__init__.py`. `TOOL_SCHEMAS` is also exported —
a list of Anthropic-format JSON schema dicts you can pass directly to
`client.messages.create(tools=TOOL_SCHEMAS)`.

---

## `manage_curriculum` — Lesson / Curriculum Tool

**File:** `lesson_generator.py`

Controls the learning structure. Think of it as managing a Notion-style database:
- A **Course** = a database
- A **Module** = a category / grouped view
- A **Lesson** = a page with properties

### Actions

| Action | Key parameters | Returns |
|---|---|---|
| `create_course` | title, topic, level, goal, hours_per_week | course dict |
| `add_module` | course_id, title, order_index | module dict |
| `add_lesson` | module_id, title, order_index, objective?, content?, tags? | lesson dict + `flashcards: []` |
| `update_lesson` | lesson_id, [any lesson fields] | updated lesson dict |
| `get_course` | course_id | full tree (course → modules → lessons) |
| `list_courses` | — | list of course summaries |
| `delete_course` | course_id | `{deleted: true}` |
| `search_lessons` | query, course_id? | matching lessons |

The `add_lesson` return includes `"flashcards": []` as a hint — the agent should immediately
call `manage_flashcards(action="create", ...)` to populate cards for the new lesson.

---

## `manage_flashcards` — Flashcard Tool

**File:** `flashcard_tool.py`

Stores and retrieves flashcards. Flashcards live only in the database; they are
**not** published to Notion.

### Actions

| Action | Key parameters | Returns |
|---|---|---|
| `create` | lesson_id, cards=[{front, back, tags?}] | `{flashcards: [...], created: N}` |
| `list` | lesson_id OR course_id, tags? (filter) | `{flashcards: [...], total: N}` |
| `get` | flashcard_id | single flashcard dict |
| `delete` | lesson_id OR flashcard_id | `{deleted: N}` |

Each card: `{"front": "...", "back": "...", "tags": [...]}`

---

## `manage_quiz` — Quiz Tool

**File:** `quiz_tool.py`

Stores quiz questions and scores submitted answers. The Streamlit app uses this data.

### Question types
- `"single"` — one correct answer (`correct_answer: str`)
- `"multi"` — multiple correct answers (`correct_answers: list[str]`)

No open-ended questions. Scoring: 70% to pass.

### Actions

| Action | Key parameters | Returns |
|---|---|---|
| `create` | lesson_id, questions, max_score? | quiz attempt dict |
| `submit` | attempt_id, answers=[{question_index, selected}] | scored attempt |
| `get` | attempt_id | attempt with questions |
| `list` | lesson_id | `{attempts: [...], total: N}` |
| `results` | attempt_id | per-question breakdown |

---

## `manage_notion_page` — Notion Tool

**File:** `notion_tool.py`

One-way export to Notion. The database is always the source of truth.

### Structure published to Notion
```
[Root page]
  └── Course page
        └── Curriculum database
              ├── Module rows
              └── Lesson rows (with objective, content, tags)
```

Flashcards are never published to Notion.

### Actions

| Action | Key parameters | Returns |
|---|---|---|
| `publish_course` | course_id | `{course_page_id, database_id, pages_created}` |
| `query_page` | page_id | Notion page metadata |
| `update_page` | page_id, properties | updated page metadata |
| `delete_page` | page_id | `{archived: true}` |
| `sync_status` | course_id | `{synced: [...], unsynced: [...]}` |

Requires `NOTION_API_KEY` and `NOTION_ROOT_PAGE_ID` in `.env`.

---

## Error handling

All tools raise `ValueError` for invalid inputs (missing records, bad action names, etc.).
Wrap tool calls in try/except in your agent loop:

```python
try:
    result = manage_curriculum(action="get_course", course_id=99)
except ValueError as e:
    # Tell the agent what went wrong and let it retry or correct
    print(f"Tool error: {e}")
```
