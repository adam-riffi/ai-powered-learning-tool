# Learnly — AI-Powered Learning Assistant

A Streamlit application that generates structured courses from text or PDF content,
then lets users study via flashcards and quizzes. Course data is persisted in a
database and can optionally be published to Notion.

---

## Architecture overview

```
┌─────────────────────────────────────────────────┐
│               Streamlit App                     │
│  0_Generate  →  app.py  →  1_Take_Quiz          │
│                          →  2_Results           │
│                          →  3_Flashcards        │
│                          →  4_notion_connect    │
│                          →  5_login             │
└────────────────────┬────────────────────────────┘
                     │
              ┌──────▼──────┐
              │   agent.py  │  ← Groq LLM (llama3-70b-8192)
              └──────┬──────┘
                     │ calls
        ┌────────────┼────────────┬───────────────┐
        ▼            ▼            ▼               ▼
manage_curriculum  manage_     manage_quiz  manage_notion_page
(lesson_generator) flashcards  (quiz_tool)  (notion_tool)
        │            │            │               │
        └────────────┴────────────┘               │
                     │                            │
              ┌──────▼──────┐              ┌──────▼──────┐
              │  SQLAlchemy │              │  Notion API  │
              │  Database   │              └─────────────┘
              └─────────────┘
```

**Key design decisions:**

| Decision | Rationale |
|---|---|
| LLM only in `agent.py` | Tools are agent-agnostic — any LLM or framework can use them |
| SQLite default | Zero config for development and testing |
| Flashcards not in Notion | Notion is a read-only export; flashcards are study-only data |
| DB = source of truth | Notion sync is one-way; never read from Notion to update the DB |
| `get_db()` context manager | Automatic commit/rollback, safe for concurrent calls |
| `user_id` scoping | Required when creating courses and flashcards; optional for reads |

---

## Project structure

```
learn_ai/
├── agent.py            Course generation engine (Groq + tool calls)
├── config.py           Settings loaded lazily from .env / Streamlit secrets
├── database.py         SQLAlchemy engine, session, init_db()
├── models.py           ORM models: Course, Module, Lesson, Flashcard, QuizAttempt
│
├── tools/              The four agent tools
│   ├── lesson_generator.py   manage_curriculum
│   ├── flashcard_tool.py     manage_flashcards
│   ├── quiz_tool.py          manage_quiz
│   └── notion_tool.py        manage_notion_page
│
├── quiz_app/           Streamlit application
│   ├── app.py                Home / quiz setup
│   ├── auth.py               OAuth helpers (Google + GitHub)
│   ├── auth_guard.py         require_auth(), render_sidebar_user()
│   └── pages/
│       ├── 0_Generate.py     Course creation (text or PDF)
│       ├── 1_Take_Quiz.py    Quiz interface
│       ├── 2_Results.py      Scoring and per-question breakdown
│       ├── 3_Flashcards.py   Flip-card study mode
│       ├── 4_notion_connect.py  Notion token + publish UI
│       └── 5_login.py        OAuth login page
│
├── prompts/            Agent system prompt and per-tool guidance
│   ├── agent.md
│   ├── lesson_generator.md
│   ├── flashcard_tool.md
│   ├── quiz_tool.md
│   └── notion_tool.md
│
└── tests/              Pytest suite — fully offline, in-memory SQLite
    ├── conftest.py
    ├── test_lesson_generator.py
    ├── test_flashcard_tool.py
    ├── test_quiz_tool.py
    └── test_notion_tool.py
```

---

## Setup

### 1. Create a virtual environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your values
```

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | No | Defaults to `sqlite:///./learn_ai.db` |
| `GROQ_API_KEY` | **Yes** | Free key at [console.groq.com](https://console.groq.com) |
| `GROQ_MODEL` | No | Defaults to `llama3-70b-8192` |
| `NOTION_API_KEY` | No | Only required if using Notion sync via `.env` |
| `NOTION_ROOT_PAGE_ID` | No | Only required if using Notion sync via `.env` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | No | Required for Google OAuth |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | No | Required for GitHub OAuth |
| `APP_BASE_URL` | No | Defaults to `http://localhost:8501` |

### 4. Initialise the database

```bash
python -c "from database import init_db; init_db(); print('DB ready')"
```

---

## Running the app

```bash
streamlit run quiz_app/app.py
```

The app opens at `http://localhost:8501`. Log in via Google or GitHub,
then navigate to **Create a course** to generate your first course.

---

## App flow

```
Login (5_login.py)
  └── OAuth callback → session_state["user"]

Create a course (0_Generate.py)
  ├── Paste text or upload PDF
  ├── Set title, level, optional instructions
  └── run_agent_chunked() → Groq LLM → tool calls → DB

Home / Quiz setup (app.py)
  ├── Select courses and lessons
  ├── Configure questions per lesson and type filter
  ├── Start Quiz → 1_Take_Quiz.py
  └── Study Flashcards → 3_Flashcards.py

Take Quiz (1_Take_Quiz.py)
  ├── Single-answer: radio buttons
  ├── Multi-select: checkboxes
  └── Submit All → 2_Results.py

Results (2_Results.py)
  ├── Overall score and pass rate
  ├── Per-lesson breakdown with correct/wrong indicators
  └── Retry Failed Questions

Notion Connection (4_notion_connect.py)
  ├── Enter integration token and root page ID
  └── Publish / republish courses to Notion
```

---

## Course generation pipeline

`run_agent_chunked()` in `agent.py` processes content in the following steps:

1. **Injection check** — rejects content containing prompt injection patterns.
2. **Educational validation** — lightweight keyword heuristic + LLM classifier.
3. **Structure analysis** — LLM proposes a module/lesson plan proportional to content length.
4. **DB creation** — creates the `Course` and `Module` rows via `manage_curriculum`.
5. **Per-lesson generation** — for each lesson, calls the LLM to produce:
   - Structured lesson content (title, objective, markdown body)
   - 5 flashcards (`manage_flashcards`)
   - 3 MCQ questions (`manage_quiz`)
6. **Notion publish** (optional) — `manage_notion_page(action="publish_course", ...)`.

A configurable pause (`pause_between_chunks`, default 1.5 s) is inserted between
Groq API calls to respect rate limits.

---

## Using the tools directly

```python
from tools import manage_curriculum, manage_flashcards, manage_quiz, manage_notion_page

# Create a course
course = manage_curriculum(
    action="create_course",
    user_id="your-user-uuid",
    title="Python Basics",
    topic="Python",
    level="beginner",
    goal="Write simple scripts",
    hours_per_week=5,
)
course_id = course["id"]
```

All tools are also available as Anthropic-compatible schemas via `TOOL_SCHEMAS`:

```python
from tools import TOOL_SCHEMAS
import anthropic

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=4096,
    tools=TOOL_SCHEMAS,
    messages=[{"role": "user", "content": "Create a Python course for beginners."}],
)
```

---

## Running tests

```bash
pytest tests/ -v
```

> ⚠️ **Known issue:** The test suite is currently outdated relative to the tool
> implementations. `test_flashcard_tool.py` and `test_lesson_generator.py` call
> `manage_flashcards(action="create", ...)` and `manage_curriculum(action="create_course", ...)`
> without the `user_id` parameter that the tools now require. These tests will raise
> `ValueError("'user_id' is required")` and fail until updated.

All tests are fully offline — no API keys or network access needed.
An in-memory SQLite database is used and rolled back after each test.

```bash
# Single file
pytest tests/test_quiz_tool.py -v

# Single test class
pytest tests/test_quiz_tool.py::TestSubmitSingle -v

# Stop on first failure
pytest tests/ -x
```

---

## Database

SQLite by default (`learn_ai.db` in the project root).
Switch to PostgreSQL by setting `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql://user:password@localhost:5432/learn_ai
```

### Schema

```
Course  (user_id, title, topic, level, goal, hours_per_week, status, notion_*)
  └── Module  (course_id, title, description, order_index)
        └── Lesson  (module_id, title, objective, content, tags, is_completed)
              ├── Flashcard  (front, back, tags)        ← NOT synced to Notion
              └── QuizAttempt  (questions, answers, score, passed, weak_areas)
```

---

## Notion integration

Notion is an **export-only** destination. The DB is always the source of truth.

**To connect via the UI:** navigate to **Notion Connection** and enter your
integration token and root page ID. The token is stored in browser session state only.

**Structure published on sync:**
```
[Root page]
  └── Course page
        ├── Course info callout
        └── Curriculum database
              ├── Module rows  (Type = Module)
              └── Lesson rows  (Type = Lesson)
```

Flashcards are never included in Notion exports.
Running `publish_course` again will archive the old pages and recreate them.

---

## Deployment (Streamlit Cloud)

Set secrets in the Streamlit Cloud dashboard under **Settings → Secrets**:

```toml
DATABASE_URL = "postgresql://..."
GROQ_API_KEY = "gsk_..."
GOOGLE_CLIENT_ID = "..."
GOOGLE_CLIENT_SECRET = "..."
GITHUB_CLIENT_ID = "..."
GITHUB_CLIENT_SECRET = "..."
APP_BASE_URL = "https://your-app.streamlit.app"
```

All settings are read lazily at call time, so secrets injected after module
import are always visible.
