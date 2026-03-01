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
    # Nettoie les balises markdown code block
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
    """Traite une demande de création de cours (mode direct)."""
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
# Analyse automatique de la structure optimale du cours
# ---------------------------------------------------------------------------

def _analyze_course_structure(
    content: str,
    course_title: str,
    level: str,
) -> dict:
    """
    Demande au LLM d'analyser le contenu et de proposer une structure optimale :
    nombre de modules, titres des modules, nombre de leçons par module.
    Retourne un dict avec 'modules': [{'title': str, 'num_lessons': int}]
    """
    content_preview = content[:3000]
    nb_chars = len(content)

    # Heuristique de base pour orienter le LLM
    if nb_chars < 2000:
        hint = "Le contenu est court (< 2000 caractères). Propose 1-2 modules avec 1-2 leçons chacun."
    elif nb_chars < 6000:
        hint = "Le contenu est moyen (2000-6000 caractères). Propose 2-3 modules avec 2 leçons chacun."
    else:
        hint = "Le contenu est long (> 6000 caractères). Propose 3-4 modules avec 2-3 leçons chacun."

    raw = _llm_json(
        system=(
            "Tu es un expert en ingénierie pédagogique. "
            "Tu analyses du contenu de cours et proposes une structure optimale. "
            "Tu réponds UNIQUEMENT en JSON valide, sans explication."
        ),
        prompt=(
            f"Analyse ce contenu pour un cours intitulé \"{course_title}\" (niveau : {level}).\n"
            f"{hint}\n\n"
            f"Réponds UNIQUEMENT avec ce JSON (sans markdown, sans explication) :\n"
            f'{{"modules": [{{"title": "Titre du module", "num_lessons": 2}}]}}\n\n'
            f"Règles :\n"
            f"- Les titres de modules doivent refléter précisément les grandes thématiques du contenu\n"
            f"- num_lessons entre 1 et 3 selon la densité du contenu pour ce module\n"
            f"- Maximum 5 modules au total\n\n"
            f"Contenu :\n{content_preview}"
        ),
        max_tokens=600,
    )

    try:
        data = json.loads(raw)
        modules = data.get("modules", [])
        if isinstance(modules, list) and len(modules) > 0:
            # Validation et nettoyage
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

    # Fallback : structure par défaut basée sur la taille
    if nb_chars < 2000:
        return {"modules": [{"title": course_title, "num_lessons": 2}]}
    elif nb_chars < 5000:
        return {"modules": [
            {"title": f"Partie 1 — {course_title}", "num_lessons": 2},
            {"title": f"Partie 2 — {course_title}", "num_lessons": 2},
        ]}
    else:
        return {"modules": [
            {"title": f"Module {i+1}", "num_lessons": 2}
            for i in range(3)
        ]}


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
    """
    Génère le contenu d'une leçon en markdown pur (pas de JSON).
    On utilise des séparateurs textuels pour extraire titre, objectif et contenu.
    Cela évite tout problème de JSON imbriqué ou tronqué.
    """
    time.sleep(pause)

    client = Groq(api_key=settings.groq_api_key)
    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un tuteur pédagogique expert. "
                "Tu génères du contenu de cours clair, détaillé et pédagogique. "
                "Tu suis EXACTEMENT le format demandé, sans ajouter de JSON ni de balises supplémentaires."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Génère la leçon {lesson_index + 1}/{num_lessons} "
                f"pour le module \"{module_title}\" (niveau : {level}).\n\n"
                f"Réponds en suivant EXACTEMENT ce format (remplace les crochets par le vrai contenu) :\n\n"
                f"TITRE: [Titre précis et descriptif de la leçon]\n\n"
                f"OBJECTIF: [L\'étudiant sera capable de ...]\n\n"
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

    # Parse le format TITRE / OBJECTIF / CONTENU
    title = f"Leçon {lesson_index + 1} — {module_title}"
    objective = "Comprendre et appliquer les concepts clés de cette leçon."
    content_md = ""

    import re as _re

    # Extrait TITRE
    m = _re.search(r'^TITRE\s*:\s*(.+)$', raw, _re.MULTILINE)
    if m:
        title = m.group(1).strip()

    # Extrait OBJECTIF
    m = _re.search(r'^OBJECTIF\s*:\s*(.+)$', raw, _re.MULTILINE)
    if m:
        objective = m.group(1).strip()

    # Extrait CONTENU (tout ce qui suit "CONTENU:")
    m = _re.search(r'^CONTENU\s*:\s*\n?(.*)', raw, _re.MULTILINE | _re.DOTALL)
    if m:
        content_md = m.group(1).strip()
    else:
        # Fallback : si le format n'est pas respecté, on prend tout sauf les 2 premières lignes
        lines = raw.split("\n")
        content_md = "\n".join(lines[2:]).strip() if len(lines) > 2 else raw

    # Sécurité : si le contenu ressemble à du JSON, on le rejette et on utilise le chunk
    if content_md.strip().startswith("{"):
        content_md = f"## {title}\n\n{chunk[:2000]}"

    return {
        "title": title,
        "objective": objective,
        "content": content_md,
    }

def _generate_flashcards(
    lesson_title: str,
    lesson_content: str,
    pause: float,
) -> list[dict]:
    time.sleep(pause)
    raw = _llm_json(
        system=(
            "Tu es un expert en création de flashcards pédagogiques. "
            "Tu réponds UNIQUEMENT en JSON valide (tableau), sans markdown autour."
        ),
        prompt=(
            f"Génère 4 flashcards pour la leçon \"{lesson_title}\".\n\n"
            f"Réponds UNIQUEMENT avec un tableau JSON :\n"
            f'[{{"front": "Question précise ?", "back": "Réponse claire et concise.", "tags": ["tag1"]}}]\n\n'
            f"Règles :\n"
            f"- Les questions doivent tester la compréhension, pas la mémorisation bête\n"
            f"- Les réponses doivent être courtes et claires (1-2 phrases)\n"
            f"- Les tags reflètent le thème de la flashcard\n\n"
            f"Basé sur :\n{lesson_content[:2000]}"
        ),
        max_tokens=800,
    )
    try:
        cards = json.loads(raw)
        if isinstance(cards, list) and len(cards) > 0:
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
        system=(
            "Tu es un expert en création de QCM pédagogiques. "
            "Tu réponds UNIQUEMENT en JSON valide (tableau), sans markdown autour."
        ),
        prompt=(
            f"Génère 3 questions QCM pour la leçon \"{lesson_title}\".\n\n"
            f"Réponds UNIQUEMENT avec un tableau JSON :\n"
            f'[{{"question": "Question claire ?", '
            f'"options": ["Option A", "Option B", "Option C", "Option D"], '
            f'"correct_answer": "Option A", "type": "single"}}]\n\n'
            f"Règles :\n"
            f"- Les questions testent la compréhension réelle du contenu\n"
            f"- correct_answer doit être EXACTEMENT l'une des options\n"
            f"- Les distracteurs (mauvaises réponses) doivent être plausibles\n\n"
            f"Basé sur :\n{lesson_content[:2000]}"
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
        # Essaye de couper sur un saut de ligne pour ne pas couper au milieu d'un paragraphe
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


# ---------------------------------------------------------------------------
# run_agent_chunked : structure automatique + génération déterministe
# ---------------------------------------------------------------------------

def run_agent_chunked(
    content: str,
    course_title: str,
    level: str,
    num_modules: int,        # conservé pour compatibilité, mais ignoré si structure auto
    num_lessons: int,        # conservé pour compatibilité, mais ignoré si structure auto
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
    - Analyse automatique du contenu pour définir la structure optimale
    - La structure (cours + modules) est créée DIRECTEMENT en Python via manage_curriculum
    - Le contenu (leçons, flashcards, quiz) est généré via des appels LLM JSON simples
    """
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY n'est pas défini.")

    def notify(msg: str) -> None:
        if on_text:
            on_text(msg)

    # ── Étape 0 : Analyse automatique de la structure optimale ───────────────
    if on_chunk_start:
        on_chunk_start(0, 1)  # placeholder, on ne connaît pas encore le total

    notify("🔍 Analyse du contenu pour déterminer la structure optimale...")

    structure = _analyze_course_structure(
        content=content,
        course_title=course_title,
        level=level,
    )
    modules_plan = structure["modules"]  # [{"title": str, "num_lessons": int}]

    total_steps = len(modules_plan) + 1
    notify(
        f"📐 Structure définie : {len(modules_plan)} module(s) — "
        + ", ".join(f"{m['title']} ({m['num_lessons']} leçon(s))" for m in modules_plan)
    )

    # ── Crée le cours DIRECTEMENT en Python ──────────────────────────────────
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
        raise RuntimeError("Aucun module créé.")

    notify(f"✅ Structure créée : {len(module_ids)} module(s)")

    # ── Découpe le contenu en chunks (1 par module) ───────────────────────────
    chunks = _split_into_chunks(content, len(module_ids))

    # ── Génération des leçons par module ─────────────────────────────────────
    total_lessons_created = 0

    for mod_i, (module_id, module_title, chunk, n_lessons) in enumerate(
        zip(module_ids, module_titles, chunks, module_lesson_counts)
    ):
        if on_chunk_start:
            on_chunk_start(mod_i + 1, total_steps)

        notify(f"📚 Module {mod_i + 1}/{len(module_ids)} : {module_title} ({n_lessons} leçon(s))")

        for lesson_i in range(n_lessons):
            notify(f"  ✍️ Leçon {lesson_i + 1}/{n_lessons}...")

            lesson_data = _generate_lesson_content(
                chunk=chunk,
                module_title=module_title,
                lesson_index=lesson_i,
                num_lessons=n_lessons,
                level=level,
                extra=extra_instructions,
                pause=pause_between_chunks,
            )

            lesson_title = lesson_data.get("title", f"Leçon {lesson_i + 1} — {module_title}")
            lesson_objective = lesson_data.get("objective", "")
            lesson_content_text = lesson_data.get("content", "")

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

            total_lessons_created += 1

            # Flashcards
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

            # Quiz
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
        f"{len(module_ids)} module(s), {total_lessons_created} leçon(s), "
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