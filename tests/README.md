# Tests

Pytest test suite for all four tools. Fully offline — no API keys, no network,
no files written to disk. An in-memory SQLite database is used and rolled back
after every test.

---

## Running tests

```bash
# All tests
pytest tests/ -v

# One file
pytest tests/test_lesson_generator.py -v

# One test class
pytest tests/test_quiz_tool.py::TestSubmitSingle -v

# One test
pytest tests/test_quiz_tool.py::TestSubmitSingle::test_all_correct -v

# Stop on first failure
pytest tests/ -x

# Show print output
pytest tests/ -s
```

---

## Test files

| File | Covers |
|---|---|
| `test_lesson_generator.py` | `manage_curriculum` — all 8 actions |
| `test_flashcard_tool.py` | `manage_flashcards` — create, list, get, delete |
| `test_quiz_tool.py` | `manage_quiz` — create, submit (single + multi), get, list, results |
| `test_notion_tool.py` | `manage_notion_page` — all actions (Notion client mocked) |

---

## How isolation works (`conftest.py`)

1. **`engine` fixture** (session-scoped): creates an in-memory SQLite engine and
   runs `Base.metadata.create_all` once.

2. **`db_session` fixture** (function-scoped): wraps each test in a savepoint.
   The transaction is rolled back after the test — so every test starts with a clean DB.

3. **`override_db` fixture**: monkeypatches `database.get_db` and the `get_db` import
   inside each tool module so all DB operations go through the test session.

4. **`mock_notion` fixture**: replaces `_get_notion_client()` in `notion_tool.py` with
   a `MagicMock`. You can configure return values per test.

5. **`override_db_for_notion`**: same as `override_db` but patches `notion_tool.get_db`
   instead. Used in Notion tests alongside `mock_notion`.

---

## Adding new tests

1. Import the tool function at the top of the test file.
2. Accept `override_db` as a parameter on your test function or class method —
   this activates the in-memory DB automatically.
3. For Notion tests, accept both `override_db_for_notion` and `mock_notion`.

```python
def test_my_feature(override_db):
    result = manage_curriculum(action="list_courses")
    assert result["total"] == 0
```

---

## Why no live tests?

Real API calls (OpenAI, Notion) would make tests slow, flaky, and require credentials
in CI. The mock fixtures cover 100% of the tool logic. If you need to test Notion
integration end-to-end, add a conftest marker `@pytest.mark.live` and run with
`pytest -m live` (you'll need to implement the marker skip logic yourself).
