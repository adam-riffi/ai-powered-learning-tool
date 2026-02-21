# Tool: `manage_flashcards`

## What it does
Stores, retrieves, and deletes flashcards linked to lessons.
Flashcards live only in the database — they are NOT published to Notion.
The agent is responsible for generating the front/back content; this tool handles storage.

## When to use it
- Immediately after adding a lesson (create cards for the new lesson)
- When the user asks to review/list flashcards for a topic
- When the user asks to delete or regenerate cards for a lesson

## Actions

### `create`
Bulk-insert flashcards for a lesson.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"create"` |
| lesson_id | int | ✓ | The lesson these cards belong to |
| cards | list[dict] | ✓ | Each card: `{front, back, tags?}` |

**Card schema:**
```json
{
  "front": "What does DRY stand for?",
  "back": "Don't Repeat Yourself — a principle to avoid code duplication.",
  "tags": ["design-principles", "python"]
}
```

**Returns:** `{"flashcards": [...], "created": N}`

---

### `list`
List all flashcards for a lesson or an entire course. At least one of `lesson_id`
or `course_id` must be provided.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"list"` |
| lesson_id | int | ✗ | List cards for a specific lesson |
| course_id | int | ✗ | List all cards across a course |
| tags | list[str] | ✗ | Filter: card must have ALL listed tags |

**Returns:** `{"flashcards": [...], "total": N}`

---

### `get`
Retrieve a single flashcard by ID.

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"get"` |
| flashcard_id | int | ✓ |

---

### `delete`
Delete flashcards. Provide `lesson_id` to delete all cards for a lesson,
or `flashcard_id` to delete just one.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"delete"` |
| lesson_id | int | ✗ | Delete all cards for this lesson |
| flashcard_id | int | ✗ | Delete a single card |

**Returns:** `{"deleted": N}`

---

## Recommended card format
- **front**: A question, term, or incomplete statement
- **back**: The answer, definition, or completion
- Keep each card focused on one concept
- Use `tags` that match the lesson's tags for consistent filtering

## Example call
```json
{
  "action": "create",
  "lesson_id": 7,
  "cards": [
    {
      "front": "What is a Python list?",
      "back": "An ordered, mutable sequence that can hold items of any type.",
      "tags": ["python", "data-structures"]
    },
    {
      "front": "How do you append to a list?",
      "back": "Use list.append(item) to add an item to the end.",
      "tags": ["python", "data-structures", "methods"]
    }
  ]
}
```
