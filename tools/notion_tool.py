"""Notion integration tool.

Publishes course content (Courses → Modules → Lessons) to Notion.
The database is ALWAYS the source of truth — Notion is a read-only export.
Flashcards and quiz attempts are NOT synced to Notion.

Requires NOTION_API_KEY and NOTION_ROOT_PAGE_ID in your .env file,
OR pass api_key/root_page_id directly to publish_course for session-based auth.

Notion structure created
------------------------
Root page (from .env or session)
  └── Course page
        ├── Course info (callout block)
        └── Curriculum database
              ├── Module entries (type = Module)
              └── Lesson entries (type = Lesson, linked to module)
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from notion_client import Client

from config import settings
from database import get_db
from models import Course, Lesson, Module


# ---------------------------------------------------------------------------
# Notion client
# ---------------------------------------------------------------------------

def _get_notion_client(api_key: Optional[str] = None) -> Client:
    """Retourne un client Notion.

    Priority : api_key argument > settings.notion_api_key (.env)
    """
    key = api_key or settings.notion_api_key
    if not key:
        raise RuntimeError(
            "NOTION_API_KEY is not set. Add it to your .env file or connect via the Notion page."
        )
    return Client(auth=key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rich_text(text: str) -> list:
    """
    Retourne le format rich_text Notion.
    Si le texte dépasse 2000 chars (limite par annotation),
    le découpe en plusieurs annotations consécutives.
    """
    text = str(text)
    if len(text) <= 2000:
        return [{"text": {"content": text}}]
    # Découpe en morceaux de 2000 chars max
    chunks = [text[i:i+2000] for i in range(0, len(text), 2000)]
    return [{"text": {"content": chunk}} for chunk in chunks]


def _archive_page_if_exists(notion: Client, page_id: Optional[str]) -> None:
    """Archive (soft-delete) a Notion page if a page_id is stored."""
    if not page_id:
        return
    try:
        notion.pages.update(page_id=page_id, archived=True)
    except Exception:
        pass


def _clean_lesson_content(text: str) -> str:
    """
    Nettoie le contenu d'une lecon avant de l'envoyer a Notion.

    Le LLM produit parfois du JSON brut de plusieurs formes :
    - JSON valide : {"title": "...", "content": "## Vrai contenu"}
    - JSON multi-lignes invalide :
        {
        "title": "...",
        "content": "## Vrai contenu
    - JSON inline en debut de texte suivi de markdown

    Dans tous les cas on extrait uniquement le vrai contenu markdown.
    """
    if not text:
        return text

    stripped = text.strip()

    # Cas 1 : JSON valide sur une ligne -> extraire le champ "content"
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and "content" in data:
                return _clean_lesson_content(str(data["content"]))
        except (json.JSONDecodeError, ValueError):
            pass

        # Cas 2 : JSON multi-lignes invalide
        # Cherche le premier titre markdown (##) dans tout le texte
        match = re.search(r'(#{1,3}\s+\S)', stripped)
        if match:
            # Tout ce qui est avant le # est du JSON parasite
            return stripped[match.start():].strip()

        # Cas 3 : cherche la valeur du champ "content" avec regex (JSON invalide)
        # Gere : "content": "valeur ici..." sur une seule ligne
        match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', stripped)
        if match:
            try:
                inner = json.loads('"' + match.group(1) + '"')
                return _clean_lesson_content(inner)
            except (json.JSONDecodeError, ValueError):
                pass

        # Cas 4 : "content": " suivi du contenu sur les lignes suivantes
        match = re.search(r'"content"\s*:\s*"(.+)', stripped, re.DOTALL)
        if match:
            raw_after = match.group(1)
            # Cherche le premier titre markdown dans ce qui suit
            md_match = re.search(r'(#{1,3}\s+\S)', raw_after)
            if md_match:
                return raw_after[md_match.start():].strip().rstrip('"}').strip()

    # Cas 5 : nettoyage ligne par ligne
    # Supprime les lignes qui sont des fragments JSON purs
    lines = stripped.split("\n")
    clean_lines = []
    skip_json_header = False

    for line in lines:
        s = line.strip()

        # Detecte le debut d'un objet JSON multi-lignes
        if s == "{":
            skip_json_header = True
            continue

        # Fin du header JSON : on arrive au champ "content"
        if skip_json_header and s.startswith('"content"'):
            skip_json_header = False
            # Extrait ce qui suit "content": "
            m = re.search(r'"content"\s*:\s*"(.*)', s)
            if m:
                partial = m.group(1).rstrip('"').strip()
                if partial:
                    clean_lines.append(partial)
            continue

        # On est encore dans le header JSON -> on saute
        if skip_json_header:
            continue

        # Lignes JSON inline ({"title": ...)
        if s.startswith('{"title"') or s.startswith('{"objective"') or s.startswith('{"content"'):
            m = re.search(r'"content"\s*:\s*"(.+)', s)
            if m:
                partial = m.group(1).rstrip('"').rstrip('}').strip()
                if partial:
                    clean_lines.append(partial)
            continue

        # Lignes de proprietes JSON pures a ignorer
        if re.match(r'^\s*"(title|objective)"\s*:', s):
            continue

        clean_lines.append(line)

    result = "\n".join(clean_lines).strip()
    # Supprime les residus JSON en fin de texte
    result = result.rstrip('"} \n').strip()
    return result

def _append_blocks_in_batches(notion: Client, page_id: str, blocks: list) -> None:
    """
    Envoie des blocs à Notion par petits lots avec retry et sleep.
    - Lots de 20 blocs max (bien en dessous de la limite de 100)
    - Sleep de 0.4s entre chaque lot pour éviter le rate limit (3 req/s)
    - Retry automatique x3 en cas d'erreur 429 ou réseau
    """
    import time as _time

    BATCH_SIZE = 20
    SLEEP_BETWEEN = 0.4   # secondes entre chaque lot
    MAX_RETRIES = 3

    for i in range(0, len(blocks), BATCH_SIZE):
        batch = blocks[i:i + BATCH_SIZE]
        for attempt in range(MAX_RETRIES):
            try:
                notion.blocks.children.append(block_id=page_id, children=batch)
                break  # succès → on passe au lot suivant
            except Exception as e:
                err = str(e).lower()
                if attempt < MAX_RETRIES - 1 and ("429" in err or "rate" in err or "timeout" in err):
                    _time.sleep(2 ** attempt)  # backoff exponentiel : 1s, 2s, 4s
                else:
                    raise  # autres erreurs ou dernière tentative → on remonte
        _time.sleep(SLEEP_BETWEEN)


def _paragraph_blocks(text: str) -> list:
    """
    Crée un ou plusieurs blocs paragraph pour un texte long.
    Notion limite à 2000 chars par annotation rich_text.
    Si le texte est plus long, on crée plusieurs blocs paragraph consécutifs.
    """
    if not text:
        return []
    blocks = []
    # Découpe sur les phrases pour ne pas couper un mot au milieu
    while len(text) > 1900:
        # Cherche un point de coupure naturel (fin de phrase) avant 1900 chars
        cut = text.rfind('. ', 0, 1900)
        if cut == -1:
            cut = text.rfind(' ', 0, 1900)
        if cut == -1:
            cut = 1900
        else:
            cut += 1  # inclure le point ou l'espace
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": text[:cut].strip()}}]},
        })
        text = text[cut:].strip()
    if text:
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": text}}]},
        })
    return blocks


def _markdown_to_blocks(text: str) -> list:
    """
    Convertit du markdown simple en blocs Notion structurés.
    Gère : titres (#, ##, ###, ####), listes (- *), code (```), paragraphes.
    Les paragraphes longs sont découpés en plusieurs blocs pour respecter
    la limite Notion de 2000 chars par annotation.
    """
    blocks = []
    lines = text.split("\n")
    in_code_block = False
    code_lines: list[str] = []
    code_lang = ""

    for line in lines:
        # Bloc de code
        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_lang = line.strip()[3:].strip() or "plain text"
                code_lines = []
            else:
                in_code_block = False
                code_content = "\n".join(code_lines)
                if code_content:
                    # Notion limite le code à 2000 chars — on tronque (pas d'autre option pour ce type)
                    blocks.append({
                        "object": "block",
                        "type": "code",
                        "code": {
                            "rich_text": [{"text": {"content": code_content[:2000]}}],
                            "language": code_lang if code_lang in [
                                "python", "javascript", "typescript", "java", "c", "cpp",
                                "css", "html", "bash", "json", "sql", "markdown"
                            ] else "plain text",
                        },
                    })
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        stripped = line.strip()

        if not stripped:
            continue

        # Titres (#### traité comme heading_3, ### heading_3, ## heading_2, # heading_1)
        if stripped.startswith("#### "):
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"text": {"content": stripped[5:][:2000]}}]},
            })
        elif stripped.startswith("### "):
            blocks.append({
                "object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"text": {"content": stripped[4:][:2000]}}]},
            })
        elif stripped.startswith("## "):
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": stripped[3:][:2000]}}]},
            })
        elif stripped.startswith("# "):
            blocks.append({
                "object": "block", "type": "heading_1",
                "heading_1": {"rich_text": [{"text": {"content": stripped[2:][:2000]}}]},
            })
        # Listes à puces
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({
                "object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"text": {"content": stripped[2:][:2000]}}]},
            })
        # Listes numérotées
        elif len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in ".)" and stripped[2] == " ":
            blocks.append({
                "object": "block", "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"text": {"content": stripped[3:][:2000]}}]},
            })
        # Citation / blockquote
        elif stripped.startswith("> "):
            blocks.append({
                "object": "block", "type": "quote",
                "quote": {"rich_text": [{"text": {"content": stripped[2:][:2000]}}]},
            })
        # Paragraphe — découpage automatique si > 1900 chars
        else:
            blocks.extend(_paragraph_blocks(stripped))

    return blocks

def _create_course_page(notion: Client, course: Course, root_page_id: Optional[str] = None) -> str:
    root = root_page_id or settings.notion_root_page_id

    if root:
        parent = {"type": "page_id", "page_id": root}
    else:
        parent = {"type": "workspace", "workspace": True}

    page = notion.pages.create(
        parent=parent,
        properties={"title": {"title": _rich_text(course.title)}},
        children=[
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": _rich_text(
                        f"📖 Niveau : {course.level.value}  |  "
                        f"🎯 Objectif : {course.goal}  |  "
                        f"🏷️ Sujet : {course.topic}"
                    ),
                    "icon": {"emoji": "📚"},
                    "color": "blue_background",
                },
            }
        ],
    )
    return page["id"]


def _create_curriculum_database(notion: Client, course_page_id: str, title: str) -> str:
    db = notion.databases.create(
        parent={"type": "page_id", "page_id": course_page_id},
        title=_rich_text(f"{title} — Curriculum"),
        properties={
            "Name": {"title": {}},
            "Type": {
                "select": {
                    "options": [
                        {"name": "Module", "color": "blue"},
                        {"name": "Lesson", "color": "green"},
                    ]
                }
            },
            "Module": {"rich_text": {}},
            "Status": {
                "select": {
                    "options": [
                        {"name": "Not Started", "color": "gray"},
                        {"name": "In Progress", "color": "yellow"},
                        {"name": "Completed", "color": "green"},
                    ]
                }
            },
            "Tags": {"multi_select": {}},
        },
    )
    return db["id"]


def _get_database_properties(notion: Client, database_id: str) -> set:
    db = notion.databases.retrieve(database_id=database_id)
    return set(db.get("properties", {}).keys())


def _create_module_entry(notion: Client, database_id: str, module: Module) -> str:
    existing_props = _get_database_properties(notion, database_id)

    properties: dict = {"Name": {"title": _rich_text(module.title)}}
    if "Type" in existing_props:
        properties["Type"] = {"select": {"name": "Module"}}
    if "Module" in existing_props:
        properties["Module"] = {"rich_text": _rich_text(module.title)}

    # Contenu du module : description si disponible
    children = []
    if module.description:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(module.description),
                "icon": {"emoji": "📦"},
                "color": "blue_background",
            },
        })

    page = notion.pages.create(
        parent={"type": "database_id", "database_id": database_id},
        properties=properties,
        children=children,
    )
    return page["id"]


def _create_lesson_entry(
    notion: Client, database_id: str, lesson: Lesson, module_title: str
) -> str:
    existing_props = _get_database_properties(notion, database_id)

    # ── Construction des blocs de contenu ────────────────────────────────────
    children = []

    # Bloc objectif
    if lesson.objective:
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(f"🎯 Objectif : {lesson.objective}"),
                "icon": {"emoji": "🎯"},
                "color": "green_background",
            },
        })

    # Diviseur visuel
    if lesson.objective and lesson.content:
        children.append({"object": "block", "type": "divider", "divider": {}})

    # Contenu markdown → blocs Notion structurés (avec nettoyage défensif)
    if lesson.content:
        raw = lesson.content
        # Déséchappe les \n littéraux que le LLM insère parfois dans les strings JSON
        raw = raw.replace('\\n', '\n').replace('\\t', '\t')
        clean_content = _clean_lesson_content(raw)
        content_blocks = _markdown_to_blocks(clean_content)
        children.extend(content_blocks)

    # ── Propriétés de la page ─────────────────────────────────────────────────
    properties: dict = {"Name": {"title": _rich_text(lesson.title)}}
    if "Type" in existing_props:
        properties["Type"] = {"select": {"name": "Lesson"}}
    if "Module" in existing_props:
        properties["Module"] = {"rich_text": _rich_text(module_title)}
    if "Status" in existing_props:
        properties["Status"] = {
            "select": {"name": "Completed" if lesson.is_completed else "Not Started"}
        }
    if "Tags" in existing_props:
        properties["Tags"] = {"multi_select": [{"name": t} for t in (lesson.tags or [])]}

    import time as _time

    # Crée la page avec les 20 premiers blocs seulement (sécurité rate limit)
    first_batch = children[:20]
    rest = children[20:]

    page = notion.pages.create(
        parent={"type": "database_id", "database_id": database_id},
        properties=properties,
        children=first_batch,
    )
    page_id = page["id"]

    # Envoie le reste du contenu par petits lots avec sleep
    if rest:
        _time.sleep(0.5)  # pause après la création de la page
        _append_blocks_in_batches(notion, page_id, rest)

    return page_id


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------

def manage_notion_page(action: str, **kwargs: Any) -> dict:
    """Create, query, update, or delete Notion pages for a course.

    Actions
    -------
    publish_course / query_page / update_page / delete_page / sync_status

    Optional kwargs for session-based auth (overrides .env):
        api_key      : str  — Notion integration token
        root_page_id : str  — Notion root page ID
    """
    action = action.strip().lower()

    if action == "publish_course":
        return _publish_course(**kwargs)
    elif action == "query_page":
        return _query_page(**kwargs)
    elif action == "update_page":
        return _update_page(**kwargs)
    elif action == "delete_page":
        return _delete_page(**kwargs)
    elif action == "sync_status":
        return _sync_status(**kwargs)
    else:
        raise ValueError(
            f"Unknown action '{action}'. Valid actions: publish_course, query_page, "
            "update_page, delete_page, sync_status"
        )


# ---------------------------------------------------------------------------
# Action implementations
# ---------------------------------------------------------------------------

def _publish_course(
    course_id: int,
    api_key: Optional[str] = None,
    root_page_id: Optional[str] = None,
    **_: Any,
) -> dict:
    notion = _get_notion_client(api_key=api_key)

    with get_db() as db:
        course = db.get(Course, int(course_id))
        if not course:
            raise ValueError(f"Course {course_id} not found")

        # Mémorise l'ancienne page avant de créer la nouvelle
        old_course_page_id = course.notion_page_id

        # ── Étape 1 : Crée la nouvelle page AVANT d'archiver l'ancienne ──
        course_page_id = _create_course_page(notion, course, root_page_id=root_page_id)
        database_id = _create_curriculum_database(notion, course_page_id, course.title)

        pages_created = 0
        for module in course.modules:
            mod_page_id = _create_module_entry(notion, database_id, module)
            module.notion_page_id = mod_page_id
            pages_created += 1

            for lesson in module.lessons:
                lesson_page_id = _create_lesson_entry(
                    notion, database_id, lesson, module.title
                )
                lesson.notion_page_id = lesson_page_id
                pages_created += 1

        from datetime import datetime
        course.notion_page_id = course_page_id
        course.notion_database_id = database_id
        course.last_synced_at = datetime.utcnow()
        db.flush()

        # ── Étape 2 : Archive l'ancienne page APRÈS que la nouvelle est créée ──
        _archive_page_if_exists(notion, old_course_page_id)

    return {
        "course_page_id": course_page_id,
        "database_id": database_id,
        "pages_created": pages_created,
    }


def _query_page(page_id: str, api_key: Optional[str] = None, **_: Any) -> dict:
    notion = _get_notion_client(api_key=api_key)
    return notion.pages.retrieve(page_id=page_id)


def _update_page(page_id: str, properties: dict, api_key: Optional[str] = None, **_: Any) -> dict:
    notion = _get_notion_client(api_key=api_key)
    return notion.pages.update(page_id=page_id, properties=properties)


def _delete_page(page_id: str, api_key: Optional[str] = None, **_: Any) -> dict:
    notion = _get_notion_client(api_key=api_key)
    notion.pages.update(page_id=page_id, archived=True)
    return {"archived": True, "page_id": page_id}


def _sync_status(course_id: int, **_: Any) -> dict:
    with get_db() as db:
        course = db.get(Course, int(course_id))
        if not course:
            raise ValueError(f"Course {course_id} not found")

        synced = []
        unsynced = []

        for module in course.modules:
            for lesson in module.lessons:
                entry = {
                    "lesson_id": lesson.id,
                    "lesson_title": lesson.title,
                    "module_title": module.title,
                    "notion_page_id": lesson.notion_page_id,
                }
                if lesson.notion_page_id:
                    synced.append(entry)
                else:
                    unsynced.append(entry)

    return {
        "synced": synced,
        "unsynced": unsynced,
        "last_synced_at": course.last_synced_at.isoformat() if course.last_synced_at else None,
    }