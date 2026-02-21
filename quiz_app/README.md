# Quiz App

A Streamlit-based quiz interface that reads questions from the database
and scores answers locally. No AI, no external calls — fully "dumb" UI.

---

## Prerequisites

The agent must have already populated the database with:
1. At least one **Course** with **Modules** and **Lessons**
2. At least one **QuizAttempt** per lesson (created via `manage_quiz(action="create", ...)`)

Without quiz questions in the database, the app will show an empty state.

---

## How to run

From the project root:

```bash
streamlit run quiz_app/app.py
```

The app opens at `http://localhost:8501`.

---

## App flow

```
app.py (Setup)
  │
  ├── Select courses (multiselect)
  ├── Select lessons (checkboxes)
  ├── Choose questions per lesson (slider, 1–20)
  ├── Choose question type (All / Single / Multi-select)
  └── Click "Start Quiz"
        │
        ▼
pages/1_Take_Quiz.py
  │
  ├── Questions grouped by lesson
  │     ├── Single-answer: radio buttons
  │     └── Multi-select: checkboxes
  └── Click "Submit All"
        │
        ▼
pages/2_Results.py
  ├── Overall score summary
  ├── Per-lesson score cards (Pass / Fail badge)
  ├── Per-question breakdown (✓ / ✗, user vs correct answer)
  └── "Retry Failed Questions" button → re-runs only wrong questions
```

---

## How questions are sourced

On "Start Quiz", the app:
1. Collects all stored `QuizAttempt.questions` for each selected lesson
2. Deduplicates by question text
3. Applies the question type filter
4. Picks up to `N` questions (from the slider)
5. Creates a **new** `QuizAttempt` in the DB for this quiz session

This means the same lesson can be quizzed multiple times with different subsets of questions.

---

## Session state keys

| Key | Contents |
|---|---|
| `quiz_attempts` | List of `{attempt_id, lesson_id, lesson_title, ...}` dicts |
| `quiz_answers` | Dict: `attempt_id → {question_index → [selected]}` |
| `quiz_current_lesson_idx` | Index of the lesson currently being answered |

The session is cleared when the user clicks "New Quiz" on the Results page.

---

## Troubleshooting

**"No courses found"** — The agent hasn't created any courses yet.

**"No quiz questions"** — The agent created the lesson but didn't call
`manage_quiz(action="create", lesson_id=..., questions=[...])`.

**Questions from wrong lessons mixing** — Check that `lesson_id` values are correct
when the agent calls `manage_quiz(action="create", ...)`.
