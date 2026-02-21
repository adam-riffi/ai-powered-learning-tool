# Learn AI — Learning Assistant Tool Suite

A set of Python tools for an AI learning assistant agent.
The agent uses these tools to build curricula, store flashcards, create quizzes, and publish content to Notion.

**No AI/LLM calls exist in this codebase.** The tools are pure database operations and Notion API calls.
Your agent (built separately) is responsible for generating content and deciding when to call each tool.

---

## Project structure

```
learn_ai/
├── config.py           Settings loaded from .env
├── database.py         SQLAlchemy engine, session, init_db()
├── models.py           All ORM models (Course, Module, Lesson, Flashcard, QuizAttempt)
│
├── tools/              The four agent tools (see tools/README.md)
│   ├── lesson_generator.py
│   ├── flashcard_tool.py
│   ├── quiz_tool.py
│   └── notion_tool.py
│
├── quiz_app/           Streamlit quiz UI (see quiz_app/README.md)
│   ├── app.py
│   └── pages/
│
├── prompts/            Agent guidance documents (see prompts/README.md)
│   ├── lesson_generator.md
│   ├── flashcard_tool.md
│   ├── quiz_tool.md
│   └── notion_tool.md
│
└── tests/              Pytest test suite (see tests/README.md)
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

Minimum required:
- `DATABASE_URL` — defaults to SQLite (`sqlite:///./learn_ai.db`), no setup needed
- `NOTION_API_KEY` + `NOTION_ROOT_PAGE_ID` — only required if using `notion_tool`

### 4. Initialise the database

```python
from database import init_db
init_db()
```

Or run it as a quick check:

```bash
python -c "from database import init_db; init_db(); print('DB ready')"
```

---

## Using the tools

Import and call directly:

```python
from tools import manage_curriculum, manage_flashcards, manage_quiz, manage_notion_page

# Create a course
course = manage_curriculum(
    action="create_course",
    title="Python Basics",
    topic="Python",
    level="beginner",
    goal="Write simple scripts",
    hours_per_week=5,
)
print(course["id"])  # use this course_id in follow-up calls
```

For your agent, import `TOOL_SCHEMAS` and pass it to your Anthropic client:

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

All tests are fully offline — no API keys needed.

---

## Running the quiz app

```bash
streamlit run quiz_app/app.py
```

The app reads quiz questions from the database. The agent must have created at least one course
with lessons and quiz questions before the app is useful.

---

## Database

SQLite by default (`learn_ai.db` in the project root).
Switch to PostgreSQL by setting `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql://user:password@localhost:5432/learn_ai
```

---

## Key design decisions

| Decision | Rationale |
|---|---|
| No AI in the tools | Tools are agent-agnostic — any LLM or framework can use them |
| SQLite default | Zero config for development and testing |
| Flashcards not in Notion | Notion is a read-only export; flashcards are study-only data |
| DB = source of truth | Notion sync is one-way; never read from Notion to update the DB |
| `get_db()` context manager | Automatic commit/rollback, safe for concurrent calls |
