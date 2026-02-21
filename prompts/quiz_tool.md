# Tool: `manage_quiz`

## What it does
Stores quiz questions for lessons and scores submitted answers.
No AI is involved in scoring — it is deterministic (exact match).
The Streamlit quiz app reads from this tool's data.

## Question types
- **`single`** — one correct answer. Matched as exact string (case-insensitive).
- **`multi`** — multiple correct answers. User must select the exact set.

No open-ended questions. All questions must have a defined `options` list
and a `correct_answer` / `correct_answers` field.

## Scoring
- Each question = `max_score / num_questions` points.
- Multi-select: full credit only (no partial).
- Pass threshold: 70%.

## When to use it
- After creating a lesson, create quiz questions for it.
- The Streamlit app will serve these questions to the learner.
- After the learner submits, call `results` to review performance.

---

## Actions

### `create`
Store a set of questions as a new quiz attempt for a lesson.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"create"` |
| lesson_id | int | ✓ | The lesson being quizzed |
| questions | list[dict] | ✓ | See schema below |
| max_score | float | ✗ | Defaults to 10 × num_questions |

**Question schema — single answer:**
```json
{
  "question": "What keyword defines a function in Python?",
  "options": ["def", "func", "function", "define"],
  "correct_answer": "def",
  "type": "single"
}
```

**Question schema — multi-select:**
```json
{
  "question": "Which of the following are Python data types?",
  "options": ["list", "vector", "dict", "table"],
  "correct_answers": ["list", "dict"],
  "type": "multi"
}
```

**Returns:** quiz attempt dict with `id` (attempt_id).

---

### `submit`
Score a completed quiz. Called by the Streamlit app automatically.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"submit"` |
| attempt_id | int | ✓ | |
| answers | list[dict] | ✓ | See schema below |

**Answer schema:**
```json
{"question_index": 0, "selected": ["def"]}
```
`selected` is always a list, even for single-answer questions.

**Returns:** scored attempt with `score`, `passed`, `weak_areas` (list of wrong question indices).

---

### `get`
Retrieve a quiz attempt with its questions (and answers if submitted).

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"get"` |
| attempt_id | int | ✓ |

---

### `list`
List all attempts for a lesson (most recent first).

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"list"` |
| lesson_id | int | ✓ |

**Returns:** `{"attempts": [...], "total": N}` — summaries, no questions.

---

### `results`
Detailed per-question breakdown. Only available after submission.

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"results"` |
| attempt_id | int | ✓ |

**Returns:** full breakdown with `is_correct`, user answer, correct answer, percentage.

---

## Example: creating a quiz
```json
{
  "action": "create",
  "lesson_id": 4,
  "questions": [
    {
      "question": "What does `len()` return?",
      "options": [
        "The number of elements in a sequence",
        "The last element",
        "The memory address",
        "Nothing"
      ],
      "correct_answer": "The number of elements in a sequence",
      "type": "single"
    },
    {
      "question": "Which methods add items to a list?",
      "options": ["append", "push", "extend", "add"],
      "correct_answers": ["append", "extend"],
      "type": "multi"
    }
  ]
}
```
