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


def _load_instructions() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Tu es un tuteur pédagogique. "
        "Crée des cours complets avec leçons, flashcards et quiz "
        "en utilisant les outils disponibles."
    )


# ---------------------------------------------------------------------------
# Dispatch des appels d'outils
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
    try:
        result = fn(**arguments)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

def run_agent(
    user_message: str,
    on_text: Callable[[str], None] | None = None,
    on_tool_call: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str], None] | None = None,
    publish_to_notion: bool = False,
) -> str:
    """Traite une demande de création de cours.

    Parameters
    ----------
    user_message : str
        La demande (ex: "Crée un cours sur Python pour débutants").
    on_text : callable, optional
        Appelé à chaque message textuel produit. Signature : on_text(text: str)
    on_tool_call : callable, optional
        Appelé avant l'exécution d'un outil. Signature : on_tool_call(name: str, args: dict)
    on_tool_result : callable, optional
        Appelé avec le résultat d'un outil. Signature : on_tool_result(name: str, result: str)
    publish_to_notion : bool
        Si True, publie le cours sur Notion après création.

    Returns
    -------
    str
        Le dernier message textuel produit.
    """
    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY n'est pas défini. "
            "Ajoutez-le dans votre fichier .env."
        )

    client = Groq(api_key=settings.groq_api_key)
    instructions = _load_instructions()

    notion_instruction = ""
    if publish_to_notion:
        notion_instruction = (
            "\n\nUne fois le cours créé en base de données, "
            "publie-le sur Notion avec manage_notion_page(action='publish_course', ...)."
        )

    messages: list[dict] = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": user_message + notion_instruction},
    ]

    last_text = ""
    max_iterations = 40

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            max_tokens=4096,
        )

        choice = response.choices[0]
        message = choice.message

        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in (message.tool_calls or [])
            ] or None,
        })

        if message.content:
            last_text = message.content
            if on_text:
                on_text(message.content)

        if not message.tool_calls:
            break

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            if on_tool_call:
                on_tool_call(tool_name, arguments)

            result = _execute_tool(tool_name, arguments)

            if on_tool_result:
                on_tool_result(tool_name, result)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    return last_text


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
        action = args.get("action", "")
        print(f"  → {name}({action})")

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