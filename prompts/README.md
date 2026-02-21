# Prompts

Reference documentation for the agent. These files explain how to use each tool,
what parameters to pass, and when to use one tool vs another.

**No code in this project reads these files.** They are written for the agent developer
to include in the agent's system prompt or context window.

---

## Files

| File | Describes |
|---|---|
| `lesson_generator.md` | `manage_curriculum` — all actions, parameters, typical workflow |
| `flashcard_tool.md` | `manage_flashcards` — create/list/get/delete, card format |
| `quiz_tool.md` | `manage_quiz` — question types, scoring, example call |
| `notion_tool.md` | `manage_notion_page` — publish flow, sync rules, cautions |

---

## How to use these in your agent

### Option A: System prompt injection
Paste the relevant `.md` content into your agent's system prompt. Include all four
if the agent needs access to all tools.

### Option B: Dynamic retrieval
Store prompt files in a vector DB. Retrieve the relevant tool description based on
the user's intent before constructing the agent's context.

### Option C: Direct reference
Hand the files to the colleague building the agent. The files are self-contained
and written to be read by a developer configuring a Claude/GPT agent.

---

## What each prompt file contains

1. **What it does** — one paragraph overview
2. **When to use it** — decision heuristics vs other tools
3. **Actions table** — every action with required/optional parameters and return shape
4. **Example call** — concrete JSON the agent should produce
5. **Workflow** — how this tool fits into the broader agent loop

---

## Important rules (repeat in your system prompt)

- The **database is always the source of truth.** Never read from Notion to update the DB.
- **Flashcards are not in Notion.** Only the lesson text is published.
- After `add_lesson`, **always call `manage_flashcards(action="create")`** to populate cards.
- Quiz questions must be stored via `manage_quiz(action="create")` before the Streamlit
  quiz app can serve them.
- All tool functions return `dict`. Check for `"id"` fields before chaining calls.
