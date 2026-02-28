"""Moteur de génération de cours.

Reçoit une demande utilisateur, appelle les outils de gestion du curriculum
et retourne un résumé de ce qui a été créé.

Utilisé par quiz_app/pages/0_Generate.py

Usage terminal :
    python agent.py "Crée un cours sur les bases de Python pour débutants"
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

# ---------------------------------------------------------------------------
# Chargement des instructions depuis prompts/agent.md
# ---------------------------------------------------------------------------

_PROMPT_PATH = Path(__file__).parent / "prompts" / "agent.md"

_TOOL_FORMAT_INSTRUCTION = """CRITICAL: Use ONLY the native tool_calls mechanism. NEVER use XML or text to call tools.\n\n"""


def _load_instructions() -> str:
    base = ""
    if _PROMPT_PATH.exists():
        base = _PROMPT_PATH.read_text(encoding="utf-8")
    else:
        base = "Tu es un tuteur pédagogique expert."
    return _TOOL_FORMAT_INSTRUCTION + base


# ---------------------------------------------------------------------------
# Conversion schemas Anthropic → Groq/OpenAI
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Dispatch des outils
# ---------------------------------------------------------------------------

_TOOLS: dict[str, Callable] = {
    "manage_curriculum": manage_curriculum,
    "manage_flashcards": manage_flashcards,
    "manage_quiz": manage_quiz,
    "manage_notion_page": manage_notion_page,
}


def _execute_tool(name: str, arguments: dict) -> str:
    fn = _TOOLS.get(name)
    if fn is None:
        return json.dumps({"error": f"Outil inconnu : {name}"})
    # Conversion de types courants pour éviter les erreurs de validation
    if name == "manage_curriculum":
        if "hours_per_week" in arguments:
            try:
                arguments["hours_per_week"] = int(arguments["hours_per_week"])
            except (ValueError, TypeError):
                arguments["hours_per_week"] = 5
        if "order_index" in arguments:
            try:
                arguments["order_index"] = int(arguments["order_index"])
            except (ValueError, TypeError):
                arguments["order_index"] = 0
    try:
        result = fn(**arguments)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Appel LLM pour générer du texte/JSON (sans tool_calls)
# ---------------------------------------------------------------------------

def _llm_json(prompt: str, system: str | None = None, max_tokens: int = 1500) -> str:
    """
    Appel LLM simple qui retourne du texte brut.
    Utilisé pour générer du JSON (contenu leçon, flashcards, quiz).
    """
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
    raw = response.choices[0].message.content or ""
    # Nettoie les balises markdown
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
    return raw


# ---------------------------------------------------------------------------
# run_agent : boucle avec tool_calls (mode sujet libre)
# ---------------------------------------------------------------------------

def run_agent(
    user_message: str,
    on_text: Callable[[str], None] | None = None,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
    publish_to_notion: bool = False,
) -> str:
    """Traite une demande de création de cours (mode sujet libre)."""
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY n'est pas défini.")

    client = Groq(api_key=settings.groq_api_key)
    instructions = _load_instructions()

    notion_instruction = ""
    if publish_to_notion:
        notion_instruction = (
            "\n\nUne fois le cours créé, publie-le sur Notion avec "
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
                    "function": {
                        "name": c["name"],
                        "arguments": json.dumps(c["arguments"]),
                    },
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


# ---------------------------------------------------------------------------
# Génération de noms de modules via LLM (JSON pur, pas de tool_calls)
# ---------------------------------------------------------------------------

def _generate_module_titles(
    content_preview: str,
    course_title: str,
    num_modules: int,
    level: str,
) -> list[str]:
    """Demande au LLM de proposer des titres de modules en JSON."""
    raw = _llm_json(
        prompt=(
            f"Propose {num_modules} titres de modules pour un cours intitulé "
            f"\"{course_title}\" (niveau {level}).\n"
            f"Réponds UNIQUEMENT avec un tableau JSON de strings, ex: [\"Module 1\", \"Module 2\"]\n"
            f"Basé sur ce contenu :\n{content_preview[:1000]}"
        ),
        max_tokens=300,
    )
    try:
        titles = json.loads(raw)
        if isinstance(titles, list) and len(titles) >= num_modules:
            return [str(t) for t in titles[:num_modules]]
    except json.JSONDecodeError:
        pass
    # Fallback si le JSON est invalide
    return [f"Module {i + 1}" for i in range(num_modules)]


# ---------------------------------------------------------------------------
# Génération contenu leçon, flashcards, quiz via LLM (JSON pur)
# ---------------------------------------------------------------------------

def _generate_lesson_content(
    chunk: str,
    module_title: str,
    lesson_index: int,
    num_lessons: int,
    level: str,
    extra: str,
    pause: float,
) -> dict:
    time.sleep(pause)
    raw = _llm_json(
        prompt=(
            f"Génère le contenu de la leçon {lesson_index + 1}/{num_lessons} "
            f"du module \"{module_title}\" (niveau {level}).\n"
            f"Réponds UNIQUEMENT en JSON valide avec ces champs :\n"
            f'{{"title": "...", "objective": "...", "content": "..."}}\n'
            f"Le champ content doit être détaillé en markdown.\n"
            f"Basé UNIQUEMENT sur :\n{chunk[:3000]}\n"
            f"{'Instructions : ' + extra if extra else ''}"
        ),
        max_tokens=1500,
    )
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "title" in data:
            return data
    except json.JSONDecodeError:
        pass
    return {
        "title": f"Leçon {lesson_index + 1}",
        "objective": "Comprendre les concepts clés",
        "content": raw or "Contenu à compléter.",
    }


def _generate_flashcards(
    lesson_title: str,
    lesson_content: str,
    pause: float,
) -> list[dict]:
    time.sleep(pause)
    raw = _llm_json(
        prompt=(
            f"Génère 4 flashcards pour la leçon \"{lesson_title}\".\n"
            f"Réponds UNIQUEMENT avec un tableau JSON :\n"
            f'[{{"front": "Question ?", "back": "Réponse.", "tags": ["tag"]}}]\n'
            f"Basé sur :\n{lesson_content[:2000]}"
        ),
        max_tokens=800,
    )
    try:
        cards = json.loads(raw)
        if isinstance(cards, list):
            return cards
    except json.JSONDecodeError:
        pass
    return [{"front": f"Concept clé de {lesson_title}", "back": "À compléter.", "tags": []}]


def _generate_quiz(
    lesson_title: str,
    lesson_content: str,
    pause: float,
) -> list[dict]:
    time.sleep(pause)
    raw = _llm_json(
        prompt=(
            f"Génère 3 questions QCM pour la leçon \"{lesson_title}\".\n"
            f"Réponds UNIQUEMENT avec un tableau JSON :\n"
            f'[{{"question": "...", "options": ["A","B","C","D"], '
            f'"correct_answer": "A", "type": "single"}}]\n'
            f"Basé sur :\n{lesson_content[:2000]}"
        ),
        max_tokens=800,
    )
    try:
        questions = json.loads(raw)
        if isinstance(questions, list):
            return questions
    except json.JSONDecodeError:
        pass
    return []


# ---------------------------------------------------------------------------
# Découpage du contenu en chunks
# ---------------------------------------------------------------------------

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
        newline_pos = content.find("\n", end)
        if newline_pos != -1 and newline_pos < end + 500:
            end = newline_pos
        chunks.append(content[start:end].strip())
        start = end
    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# run_agent_chunked : 100% Python direct, zéro tool_calls pour les leçons
# ---------------------------------------------------------------------------

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
    Génère un cours de façon entièrement déterministe :
    - La structure (cours + modules) est créée DIRECTEMENT en Python via manage_curriculum
      → zéro LLM, zéro risque de tool_use_failed
    - Le contenu (leçons, flashcards, quiz) est généré via des appels LLM JSON simples
      → pas de tool_calls, juste du JSON en réponse
    """
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY n'est pas défini.")

    def notify(msg: str) -> None:
        if on_text:
            on_text(msg)

    total_steps = num_modules + 1

    # ── Étape 0 : génère les titres des modules via LLM (JSON pur) ───────────
    if on_chunk_start:
        on_chunk_start(0, total_steps)

    notify("📐 Génération des titres de modules...")

    module_titles = _generate_module_titles(
        content_preview=content[:1500],
        course_title=course_title,
        num_modules=num_modules,
        level=level,
    )

    # ── Crée le cours DIRECTEMENT en Python (pas de tool_calls LLM) ──────────
    notify(f"💾 Création du cours \"{course_title}\" en base...")

    if on_tool_call:
        on_tool_call("manage_curriculum", {"action": "create_course", "title": course_title})

    course_result = manage_curriculum(
        action="create_course",
        title=course_title,
        topic=course_title,
        level=level,
        goal=f"Maîtriser les concepts de {course_title}",
        hours_per_week=5,
    )

    if on_tool_result:
        on_tool_result("manage_curriculum", json.dumps(course_result))

    course_id = course_result.get("id")
    if not course_id:
        raise RuntimeError("Impossible de créer le cours en base.")

    # ── Crée les modules DIRECTEMENT en Python ────────────────────────────────
    module_ids = []
    for i, title in enumerate(module_titles):
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

    if not module_ids:
        raise RuntimeError("Aucun module créé.")

    notify(f"✅ Structure créée : {len(module_ids)} module(s)")

    # ── Découpe le contenu ────────────────────────────────────────────────────
    chunks = _split_into_chunks(content, len(module_ids))

    # ── Étapes 1..N : génération des leçons par module ───────────────────────
    for mod_i, (module_id, module_title, chunk) in enumerate(
        zip(module_ids, module_titles, chunks)
    ):
        if on_chunk_start:
            on_chunk_start(mod_i + 1, total_steps)

        notify(f"📚 Module {mod_i + 1}/{len(module_ids)} : {module_title}")

        for lesson_i in range(num_lessons):
            notify(f"  ✍️ Leçon {lesson_i + 1}/{num_lessons}...")

            # Génère le contenu
            lesson_data = _generate_lesson_content(
                chunk=chunk,
                module_title=module_title,
                lesson_index=lesson_i,
                num_lessons=num_lessons,
                level=level,
                extra=extra_instructions,
                pause=pause_between_chunks,
            )

            lesson_title = lesson_data.get("title", f"Leçon {lesson_i + 1}")
            lesson_objective = lesson_data.get("objective", "")
            lesson_content_text = lesson_data.get("content", "")

            # Sauvegarde la leçon directement
            if on_tool_call:
                on_tool_call("manage_curriculum", {
                    "action": "add_lesson",
                    "module_id": module_id,
                    "title": lesson_title,
                })

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
                notify(f"  ⚠️ Leçon non créée, on continue.")
                continue

            # Génère et sauvegarde les flashcards
            notify(f"  🃏 Flashcards...")
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

            # Génère et sauvegarde le quiz
            notify(f"  ❓ Quiz...")
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

    # ── Publication Notion si demandée ───────────────────────────────────────
    if publish_to_notion:
        notify("📄 Publication sur Notion...")
        try:
            notion_result = manage_notion_page(action="publish_course", course_id=course_id)
            if on_tool_result:
                on_tool_result("manage_notion_page", json.dumps(notion_result))
        except Exception as e:
            notify(f"⚠️ Erreur Notion : {e}")

    summary = (
        f"✅ Cours \"{course_title}\" créé avec succès !\n"
        f"{len(module_ids)} module(s), {len(module_ids) * num_lessons} leçon(s), "
        f"chacune avec flashcards et quiz."
    )
    notify(summary)
    return summary


# ---------------------------------------------------------------------------
# Usage en ligne de commande
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Crée un cours d'introduction à Python pour débutants "
        "avec 2 modules et 2 leçons par module."
    )

    print(f"\nDémarrage : {prompt}\n{'─' * 60}")

    def on_text(text: str) -> None:
        print(f"\n{text}")

    def on_tool_call(name: str, args: dict) -> None:
        print(f"  → {name}({args.get('action', '')})")

    def on_tool_result(name: str, result: str) -> None:
        try:
            data = json.loads(result)
            if "id" in data:
                print(f"     ✓ id={data['id']}")
            elif "created" in data:
                print(f"     ✓ {data['created']} éléments créés")
            elif "error" in data:
                print(f"     ✗ {data['error']}")
        except Exception:
            print("     ✓ OK")

    run_agent(
        prompt,
        on_text=on_text,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
    )

    print(f"\n{'─' * 60}\nTerminé.")