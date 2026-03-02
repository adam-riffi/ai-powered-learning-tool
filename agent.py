"""Course generation engine.

Receives a user request, calls curriculum management tools,
and returns a summary of what was created.

Used by quiz_app/pages/0_Generate.py

Terminal usage:
    python agent.py "Create a Python basics course for beginners"
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable

from groq import Groq

from config import settings
from tools import (
    TOOL_SCHEMAS,
    manage_curriculum,
    manage_flashcards,
    manage_notion_page,
    manage_quiz,
)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "agent.md"

_TOOL_FORMAT_INSTRUCTION = (
    "CRITICAL: Use ONLY the native tool_calls mechanism. "
    "NEVER use XML or text to call tools.\n\n"
)


def _load_instructions() -> str:
    base = _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else "Tu es un tuteur pédagogique expert."
    return _TOOL_FORMAT_INSTRUCTION + base


def _to_groq_tools(schemas: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in schemas
    ]


_GROQ_TOOL_SCHEMAS = _to_groq_tools(TOOL_SCHEMAS)

_TOOLS: dict[str, Callable] = {
    "manage_curriculum": manage_curriculum,
    "manage_flashcards": manage_flashcards,
    "manage_quiz": manage_quiz,
    "manage_notion_page": manage_notion_page,
}


def _execute_tool(name: str, arguments: dict) -> str:
    fn = _TOOLS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    if name == "manage_curriculum":
        for key in ("hours_per_week", "order_index"):
            if key in arguments:
                try:
                    arguments[key] = int(arguments[key])
                except (ValueError, TypeError):
                    arguments[key] = 5 if key == "hours_per_week" else 0
    try:
        result = fn(**arguments)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _llm_json(prompt: str, system: str | None = None, max_tokens: int = 1500) -> str:
    """Simple LLM call returning raw text. Used for JSON generation without tool_calls."""
    client = Groq(api_key=settings.groq_api_key)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.3,
    )
    raw = (response.choices[0].message.content or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
    return raw


def run_agent(
    user_message: str,
    on_text: Callable[[str], None] | None = None,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
    publish_to_notion: bool = False,
) -> str:
    """Process a course creation request (direct mode)."""
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    client = Groq(api_key=settings.groq_api_key)
    instructions = _load_instructions()

    notion_instruction = ""
    if publish_to_notion:
        notion_instruction = (
            "\n\nOnce the course is created, publish it to Notion with "
            "manage_notion_page(action='publish_course', ...)."
        )

    messages: list[dict] = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": user_message + notion_instruction},
    ]

    last_text = ""
    max_iterations = 60

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            tools=_GROQ_TOOL_SCHEMAS,
            tool_choice="auto",
            max_tokens=2048,
        )

        choice = response.choices[0]
        message = choice.message
        text = message.content or ""
        calls = []

        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})

        assistant_msg: dict = {"role": "assistant", "content": text}
        if calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
                }
                for c in calls
            ]
        messages.append(assistant_msg)

        if text:
            last_text = text
            if on_text:
                on_text(text)

        if not calls:
            break

        for call in calls:
            if on_tool_call:
                on_tool_call(call["name"], call["arguments"])
            result = _execute_tool(call["name"], call["arguments"])
            if on_tool_result:
                on_tool_result(call["name"], result)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": result,
            })

    return last_text


def _analyze_course_structure(content: str, course_title: str, level: str) -> dict:
    """Ask the LLM to propose an optimal module/lesson structure for the given content."""
    content_preview = content[:3000]
    nb_chars = len(content)

    if nb_chars < 2000:
        hint = "Content is short (<2000 chars). Suggest 1-2 modules with 1-2 lessons each."
    elif nb_chars < 6000:
        hint = "Content is medium (2000-6000 chars). Suggest 2-3 modules with 2 lessons each."
    else:
        hint = "Content is long (>6000 chars). Suggest 3-4 modules with 2-3 lessons each."

    raw = _llm_json(
        system=(
            "You are an expert in instructional design. "
            "You analyse course content and propose an optimal structure. "
            "Respond ONLY with valid JSON, no explanation."
        ),
        prompt=(
            f"Analyse this content for a course titled \"{course_title}\" (level: {level}).\n"
            f"{hint}\n\n"
            f"Respond ONLY with this JSON (no markdown, no explanation):\n"
            f'{{"modules": [{{"title": "Module title", "num_lessons": 2}}]}}\n\n'
            f"Rules:\n"
            f"- Module titles must reflect the main themes of the content\n"
            f"- num_lessons between 1 and 3 based on content density\n"
            f"- Maximum 5 modules total\n\n"
            f"Content:\n{content_preview}"
        ),
        max_tokens=600,
    )

    try:
        data = json.loads(raw)
        modules = data.get("modules", [])
        if isinstance(modules, list) and modules:
            result = []
            for m in modules[:5]:
                if isinstance(m, dict) and "title" in m:
                    result.append({
                        "title": str(m["title"]),
                        "num_lessons": max(1, min(3, int(m.get("num_lessons", 2)))),
                    })
            if result:
                return {"modules": result}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    if nb_chars < 2000:
        return {"modules": [{"title": course_title, "num_lessons": 2}]}
    elif nb_chars < 5000:
        return {"modules": [
            {"title": f"Part 1 — {course_title}", "num_lessons": 2},
            {"title": f"Part 2 — {course_title}", "num_lessons": 2},
        ]}
    else:
        return {"modules": [{"title": f"Module {i + 1}", "num_lessons": 2} for i in range(3)]}


def _generate_lesson_content(
    chunk: str,
    module_title: str,
    lesson_index: int,
    num_lessons: int,
    level: str,
    extra: str,
    pause: float,
) -> dict:
    """Generate lesson content as plain markdown using text separators to avoid nested JSON issues."""
    time.sleep(pause)

    client = Groq(api_key=settings.groq_api_key)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert pedagogical tutor. "
                "You generate clear, detailed, and educational course content. "
                "Follow EXACTLY the requested format without adding JSON or extra tags."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Génère la leçon {lesson_index + 1}/{num_lessons} "
                f"pour le module \"{module_title}\" (niveau : {level}).\n\n"
                f"Réponds en suivant EXACTEMENT ce format (remplace les crochets par le vrai contenu) :\n\n"
                f"TITRE: [Titre précis et descriptif de la leçon]\n\n"
                f"OBJECTIF: [L'étudiant sera capable de ...]\n\n"
                f"CONTENU:\n"
                f"[Contenu détaillé en markdown : utilise ## pour les sections, ### pour les sous-sections, "
                f"- pour les listes, ``` pour le code. Minimum 400 mots. "
                f"PAS de JSON, uniquement du texte et du markdown.]\n\n"
                f"{'Instructions supplémentaires : ' + extra + chr(10) if extra else ''}"
                f"Basé UNIQUEMENT sur ce contenu :\n{chunk[:4000]}"
            ),
        },
    ]

    response = client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        max_tokens=3000,
        temperature=0.3,
    )
    raw = (response.choices[0].message.content or "").strip()

    import re as _re

    title = f"Leçon {lesson_index + 1} — {module_title}"
    objective = "Comprendre et appliquer les concepts clés de cette leçon."
    content_md = ""

    m = _re.search(r'^TITRE\s*:\s*(.+)$', raw, _re.MULTILINE)
    if m:
        title = m.group(1).strip()

    m = _re.search(r'^OBJECTIF\s*:\s*(.+)$', raw, _re.MULTILINE)
    if m:
        objective = m.group(1).strip()

    m = _re.search(r'^CONTENU\s*:\s*\n?(.*)', raw, _re.MULTILINE | _re.DOTALL)
    if m:
        content_md = m.group(1).strip()

    if not content_md:
        content_md = raw

    return {"title": title, "objective": objective, "content": content_md}


def _generate_flashcards(lesson_title: str, lesson_content: str, pause: float) -> list[dict]:
    time.sleep(pause)
    raw = _llm_json(
        system=(
            "You are an expert at creating educational flashcards. "
            "Respond ONLY with valid JSON (array), no markdown wrapping."
        ),
        prompt=(
            f"Generate 5 flashcards for the lesson \"{lesson_title}\".\n\n"
            f"Respond ONLY with a JSON array:\n"
            f'[{{"front": "Question?", "back": "Answer.", "tags": ["tag"]}}]\n\n'
            f"Rules:\n"
            f"- Questions test real understanding, not just recall\n"
            f"- Answers are concise (1-2 sentences)\n\n"
            f"Based on:\n{lesson_content[:2000]}"
        ),
        max_tokens=800,
    )
    try:
        cards = json.loads(raw)
        if isinstance(cards, list):
            return cards
    except json.JSONDecodeError:
        pass
    return []


def _generate_quiz(lesson_title: str, lesson_content: str, pause: float) -> list[dict]:
    time.sleep(pause)
    raw = _llm_json(
        system=(
            "You are an expert at creating educational MCQs. "
            "Respond ONLY with valid JSON (array), no markdown wrapping."
        ),
        prompt=(
            f"Generate 3 MCQ questions for the lesson \"{lesson_title}\".\n\n"
            f"Respond ONLY with a JSON array:\n"
            f'[{{"question": "Clear question?", '
            f'"options": ["Option A", "Option B", "Option C", "Option D"], '
            f'"correct_answer": "Option A", "type": "single"}}]\n\n'
            f"Rules:\n"
            f"- Questions test real comprehension of the content\n"
            f"- correct_answer must be EXACTLY one of the options\n"
            f"- Distractors (wrong answers) must be plausible\n\n"
            f"Based on:\n{lesson_content[:2000]}"
        ),
        max_tokens=900,
    )
    try:
        questions = json.loads(raw)
        if isinstance(questions, list):
            return questions
    except json.JSONDecodeError:
        pass
    return []


def _split_into_chunks(content: str, num_chunks: int) -> list[str]:
    if num_chunks <= 1:
        return [content]
    chunk_size = len(content) // num_chunks
    chunks = []
    start = 0
    for i in range(num_chunks):
        if i == num_chunks - 1:
            chunks.append(content[start:].strip())
            break
        end = start + chunk_size
        newline_pos = content.find("\n\n", end)
        if newline_pos != -1 and newline_pos < end + 800:
            end = newline_pos
        else:
            newline_pos = content.find("\n", end)
            if newline_pos != -1 and newline_pos < end + 200:
                end = newline_pos
        chunks.append(content[start:end].strip())
        start = end
    return [c for c in chunks if c]


def run_agent_chunked(
    content: str,
    course_title: str,
    level: str,
    num_modules: int,
    num_lessons: int,
    extra_instructions: str = "",
    on_text: Callable[[str], None] | None = None,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
    on_chunk_start: Callable[[int, int], None] | None = None,
    publish_to_notion: bool = False,
    pause_between_chunks: float = 12.0,
) -> str:
    """
    Generate a course deterministically:
    - Auto-analyses content to define optimal structure
    - Creates course + modules directly via manage_curriculum
    - Generates content (lessons, flashcards, quiz) via direct LLM JSON calls
    """
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    def notify(msg: str) -> None:
        if on_text:
            on_text(msg)

    if on_chunk_start:
        on_chunk_start(0, 1)

    notify("Analysing content to determine optimal structure...")

    structure = _analyze_course_structure(content=content, course_title=course_title, level=level)
    modules_plan = structure["modules"]

    total_steps = len(modules_plan) + 1
    notify(
        f"Structure defined: {len(modules_plan)} module(s) — "
        + ", ".join(f"{m['title']} ({m['num_lessons']} lesson(s))" for m in modules_plan)
    )

    notify(f"Creating course \"{course_title}\" in database...")

    if on_tool_call:
        on_tool_call("manage_curriculum", {"action": "create_course", "title": course_title})

    course_result = manage_curriculum(
        action="create_course",
        title=course_title,
        topic=course_title,
        level=level,
        goal=f"Master the concepts of {course_title}",
        hours_per_week=5,
    )

    if on_tool_result:
        on_tool_result("manage_curriculum", json.dumps(course_result))

    course_id = course_result.get("id")
    if not course_id:
        raise RuntimeError("Failed to create course in database.")

    module_ids = []
    module_titles = []
    module_lesson_counts = []

    for i, mod_plan in enumerate(modules_plan):
        title = mod_plan["title"]
        n_lessons = mod_plan["num_lessons"]

        if on_tool_call:
            on_tool_call("manage_curriculum", {"action": "add_module", "title": title})

        mod_result = manage_curriculum(
            action="add_module",
            course_id=course_id,
            title=title,
            order_index=i,
        )

        if on_tool_result:
            on_tool_result("manage_curriculum", json.dumps(mod_result))

        mod_id = mod_result.get("id")
        if mod_id:
            module_ids.append(mod_id)
            module_titles.append(title)
            module_lesson_counts.append(n_lessons)

    if not module_ids:
        raise RuntimeError("No modules created.")

    notify(f"Structure created: {len(module_ids)} module(s)")

    chunks = _split_into_chunks(content, len(module_ids))
    total_lessons_created = 0

    for mod_i, (module_id, module_title, chunk, n_lessons) in enumerate(
        zip(module_ids, module_titles, chunks, module_lesson_counts)
    ):
        if on_chunk_start:
            on_chunk_start(mod_i + 1, total_steps)

        notify(f"Module {mod_i + 1}/{len(module_ids)}: {module_title} ({n_lessons} lesson(s))")

        for lesson_i in range(n_lessons):
            notify(f"  Lesson {lesson_i + 1}/{n_lessons}...")

            lesson_data = _generate_lesson_content(
                chunk=chunk,
                module_title=module_title,
                lesson_index=lesson_i,
                num_lessons=n_lessons,
                level=level,
                extra=extra_instructions,
                pause=pause_between_chunks,
            )

            lesson_title = lesson_data.get("title", f"Lesson {lesson_i + 1} — {module_title}")
            lesson_objective = lesson_data.get("objective", "")
            lesson_content_text = lesson_data.get("content", "")

            if on_tool_call:
                on_tool_call("manage_curriculum", {"action": "add_lesson", "module_id": module_id, "title": lesson_title})

            lesson_result = manage_curriculum(
                action="add_lesson",
                module_id=module_id,
                title=lesson_title,
                order_index=lesson_i,
                objective=lesson_objective,
                content=lesson_content_text,
                tags=[module_title.lower().replace(" ", "-")],
            )

            if on_tool_result:
                on_tool_result("manage_curriculum", json.dumps(lesson_result))

            lesson_id = lesson_result.get("id")
            if not lesson_id:
                notify("  Lesson not created, skipping.")
                continue

            total_lessons_created += 1

            cards = _generate_flashcards(
                lesson_title=lesson_title,
                lesson_content=lesson_content_text,
                pause=pause_between_chunks,
            )
            if cards:
                if on_tool_call:
                    on_tool_call("manage_flashcards", {"action": "create", "lesson_id": lesson_id})
                fc_result = manage_flashcards(action="create", lesson_id=lesson_id, cards=cards)
                if on_tool_result:
                    on_tool_result("manage_flashcards", json.dumps(fc_result))

            questions = _generate_quiz(
                lesson_title=lesson_title,
                lesson_content=lesson_content_text,
                pause=pause_between_chunks,
            )
            if questions:
                if on_tool_call:
                    on_tool_call("manage_quiz", {"action": "create", "lesson_id": lesson_id})
                quiz_result = manage_quiz(action="create", lesson_id=lesson_id, questions=questions)
                if on_tool_result:
                    on_tool_result("manage_quiz", json.dumps(quiz_result))

    if publish_to_notion:
        notify("Publishing to Notion...")
        try:
            notion_result = manage_notion_page(action="publish_course", course_id=course_id)
            if on_tool_result:
                on_tool_result("manage_notion_page", json.dumps(notion_result))
        except Exception as e:
            notify(f"Notion error: {e}")

    summary = (
        f"Course \"{course_title}\" created successfully. "
        f"{len(module_ids)} module(s), {total_lessons_created} lesson(s), "
        f"each with flashcards and quiz."
    )
    notify(summary)
    return summary


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Create an introduction to Python course for beginners "
        "with 2 modules and 2 lessons per module."
    )

    print(f"\nStarting: {prompt}\n{'─' * 60}")

    def on_text(text: str) -> None:
        print(f"\n{text}")

    def on_tool_call(name: str, args: dict) -> None:
        print(f"  -> {name}({args.get('action', '')})")

    def on_tool_result(name: str, result: str) -> None:
        try:
            data = json.loads(result)
            if "id" in data:
                print(f"     ok id={data['id']}")
            elif "created" in data:
                print(f"     ok {data['created']} items created")
            elif "error" in data:
                print(f"     error {data['error']}")
        except Exception:
            print("     ok")

    run_agent(prompt, on_text=on_text, on_tool_call=on_tool_call, on_tool_result=on_tool_result)
    print(f"\n{'─' * 60}\nDone.")