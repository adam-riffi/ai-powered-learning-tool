# Tool: `manage_curriculum`

## What it does
Manages the full curriculum structure in the database: courses, modules, and lessons.
Use this tool as your primary write surface for building a learning programme.
Every call returns a dict — always inspect the returned IDs before chaining calls.

## When to use it
- User wants to create a new course on a topic
- User wants to add content to an existing course
- User wants to search or review existing material
- User wants to remove a course entirely

## Actions

### `create_course`
Create a new top-level course.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"create_course"` |
| title | str | ✓ | Full descriptive name |
| topic | str | ✓ | Subject area |
| level | str | ✓ | `"beginner"`, `"intermediate"`, or `"advanced"` |
| goal | str | ✓ | What the learner will be able to do |
| hours_per_week | int | ✓ | Suggested study pace |

**Returns:** course dict with `id` — save this as `course_id` for follow-up calls.

---

### `add_module`
Add a module (chapter / unit) to an existing course.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"add_module"` |
| course_id | int | ✓ | From create_course |
| title | str | ✓ | Module name |
| order_index | int | ✓ | 0-based position in course |
| description | str | ✗ | Optional summary |

**Returns:** module dict with `id`.

---

### `add_lesson`
Add a lesson to a module. After calling this, immediately call `manage_flashcards`
to populate flashcards for the lesson.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"add_lesson"` |
| module_id | int | ✓ | From add_module |
| title | str | ✓ | Lesson name |
| order_index | int | ✓ | 0-based position in module |
| objective | str | ✗ | Learning objective |
| content | str | ✗ | Full lesson text (markdown supported) |
| tags | list[str] | ✗ | Topic tags e.g. `["python", "loops"]` |

**Returns:** lesson dict with `id` and an empty `flashcards` list — this is a signal
to create flashcards next.

---

### `update_lesson`
Update any fields of an existing lesson.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"update_lesson"` |
| lesson_id | int | ✓ | Lesson to update |
| title | str | ✗ | New title |
| objective | str | ✗ | New objective |
| content | str | ✗ | New markdown content |
| tags | list[str] | ✗ | Replace tags |
| is_completed | bool | ✗ | Mark as done |

---

### `get_course`
Retrieve the full tree for a course.

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"get_course"` |
| course_id | int | ✓ |

**Returns:** course dict with nested `modules` → `lessons` (includes flashcard_count and quiz_attempt_count per lesson).

---

### `list_courses`
List all courses with summary stats.

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"list_courses"` |

---

### `delete_course`
Permanently delete a course and all its content (modules, lessons, flashcards, quiz attempts).

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"delete_course"` |
| course_id | int | ✓ |

---

### `search_lessons`
Full-text search across lesson title, objective, and content.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"search_lessons"` |
| query | str | ✓ | Search term |
| course_id | int | ✗ | Restrict to a course |

**Returns:** matching lessons (content truncated to 300 chars).

---

## Typical agent workflow

```
1. manage_curriculum(action="create_course", title="Python Basics", topic="Python",
                     level="beginner", goal="Write simple scripts", hours_per_week=5)
   → saves course_id

2. manage_curriculum(action="add_module", course_id=<id>, title="Variables",
                     order_index=0, description="...")
   → saves module_id

3. manage_curriculum(action="add_lesson", module_id=<id>, title="What is a variable?",
                     order_index=0, objective="...", content="...", tags=["variables"])
   → saves lesson_id, sees flashcards=[]

4. manage_flashcards(action="create", lesson_id=<id>, cards=[...])
   → flashcards stored

5. manage_quiz(action="create", lesson_id=<id>, questions=[...])
   → quiz stored (ready for Streamlit app)
```
