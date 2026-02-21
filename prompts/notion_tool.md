# Tool: `manage_notion_page`

## What it does
Publishes course content from the database to Notion, and lets you query,
update, or archive Notion pages.

**Important rules:**
- The **database is always the source of truth.** Never read from Notion to update the DB.
- Notion is an **export destination only** — one-way sync.
- **Flashcards are never included** in Notion exports.
- Requires `NOTION_API_KEY` and `NOTION_ROOT_PAGE_ID` in `.env`.

## Notion structure created on publish
```
[Root page from .env]
  └── Course page  (titled with course name)
        ├── Course info callout
        └── Curriculum database
              ├── Module rows  (Type = Module)
              └── Lesson rows  (Type = Lesson, linked to module by name)
```

## Actions

### `publish_course`
Create Notion pages for an entire course (modules + lessons).
Running this again will create DUPLICATE pages — check `sync_status` first.

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"publish_course"` |
| course_id | int | ✓ |

**Returns:** `{"course_page_id": "...", "database_id": "...", "pages_created": N}`

---

### `query_page`
Retrieve metadata for any Notion page by ID.

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"query_page"` |
| page_id | str | ✓ |

**Returns:** raw Notion page object.

---

### `update_page`
Update properties of a Notion page.

**Parameters:**
| Param | Type | Required | Notes |
|---|---|---|---|
| action | str | ✓ | `"update_page"` |
| page_id | str | ✓ | Notion page ID |
| properties | dict | ✓ | Notion properties object |

**Example properties:**
```json
{
  "Status": {"select": {"name": "Completed"}}
}
```

---

### `delete_page`
Archive a Notion page (Notion does not support permanent deletion via API).

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"delete_page"` |
| page_id | str | ✓ |

**Returns:** `{"archived": true, "page_id": "..."}`

---

### `sync_status`
Check which lessons have been published to Notion and which haven't.

**Parameters:**
| Param | Type | Required |
|---|---|---|
| action | str | ✓ `"sync_status"` |
| course_id | int | ✓ |

**Returns:**
```json
{
  "synced": [{"lesson_id": 1, "lesson_title": "...", "notion_page_id": "..."}],
  "unsynced": [{"lesson_id": 2, "lesson_title": "..."}],
  "last_synced_at": "2024-01-15T12:00:00"
}
```

---

## Recommended workflow

```
1. Build the full course in the DB first using manage_curriculum.
2. Check sync status:
   manage_notion_page(action="sync_status", course_id=<id>)
3. Publish if not yet published:
   manage_notion_page(action="publish_course", course_id=<id>)
4. For individual updates, use update_page with the stored notion_page_id.
```

## When NOT to use this tool
- Do not use `update_page` to change lesson content — update it in the DB with
  `manage_curriculum(action="update_lesson")` and republish instead.
- Do not use Notion page IDs to track learning state — use `is_completed` in the DB.
