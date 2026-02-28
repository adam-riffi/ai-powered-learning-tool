"""Page de génération de cours.

Deux modes :
- Sujet libre : l'app génère tout le contenu
- Contenu personnel : l'utilisateur colle du texte ou uploade un PDF,
  l'app structure et génère flashcards + quiz à partir de ce contenu.

Placement : quiz_app/pages/0_Generate.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import io
import streamlit as st
from database import init_db
from config import settings

init_db()

st.set_page_config(page_title="Créer un cours", page_icon="✨", layout="wide")

st.title("✨ Créer un cours")

# ---------------------------------------------------------------------------
# Vérification de la clé Groq
# ---------------------------------------------------------------------------
if not settings.groq_api_key:
    st.error(
        "**GROQ_API_KEY manquant.**\n\n"
        "Ajoutez votre clé dans le fichier `.env` :\n```\nGROQ_API_KEY=votre_clé_ici\n```\n\n"
        "Clé gratuite disponible sur [console.groq.com](https://console.groq.com)."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Seuil au-delà duquel on active le mode chunked
# 4000 caractères ≈ ~1000 tokens, confortable pour le tier gratuit (12k TPM)
# ---------------------------------------------------------------------------
CHUNK_THRESHOLD = 4000

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

level_map = {"Débutant": "beginner", "Intermédiaire": "intermediate", "Avancé": "advanced"}


def extract_pdf_text(uploaded_file) -> str:
    """Extrait le texte d'un PDF uploadé via Streamlit."""
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(uploaded_file.read()))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()
    except ImportError:
        st.error("pypdf n'est pas installé. Lancez : `pip install pypdf`")
        st.stop()


def run_generation(user_message: str, publish_notion: bool) -> None:
    """Lance la génération (mode sujet libre) et affiche la progression."""
    _display_generation(
        lambda on_text, on_tool_call, on_tool_result: __import__("agent").run_agent(
            user_message=user_message,
            on_text=on_text,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            publish_to_notion=publish_notion,
        )
    )


def run_generation_chunked(
    content: str,
    course_title: str,
    level: str,
    num_modules: int,
    num_lessons: int,
    extra_instructions: str,
    publish_notion: bool,
) -> None:
    """Lance la génération en mode chunked (contenu fourni) et affiche la progression."""
    from agent import run_agent_chunked

    st.divider()
    st.subheader("Progression")

    total_steps = num_modules + 1
    log_lines: list[str] = []
    status_placeholder = st.empty()
    chunk_placeholder = st.empty()
    log_placeholder = st.empty()

    def update_log(line: str) -> None:
        log_lines.append(line)
        log_placeholder.markdown("\n".join(log_lines))

    def on_text(text: str) -> None:
        # Filtre les messages de pause (affichés séparément)
        if "Pause de" in text:
            return
        update_log(f"\n💬 {text}")

    def on_tool_call(name: str, args: dict) -> None:
        icons = {
            "manage_curriculum": "📚",
            "manage_flashcards": "🃏",
            "manage_quiz": "❓",
            "manage_notion_page": "📄",
        }
        icon = icons.get(name, "🔧")
        action = args.get("action", "")
        label = args.get("title") or args.get("lesson_id") or args.get("course_id") or ""
        update_log(f"{icon} `{name}` → **{action}**{f' — *{label}*' if label else ''}")

    def on_tool_result(name: str, result: str) -> None:
        try:
            data = json.loads(result)
            if "error" in data:
                update_log(f"   ✗ `{data['error']}`")
            elif "id" in data:
                update_log(f"   ✓ id={data['id']}")
            elif "created" in data:
                update_log(f"   ✓ {data['created']} éléments créés")
            elif "pages_created" in data:
                update_log(f"   ✓ {data['pages_created']} pages publiées sur Notion")
            else:
                update_log("   ✓ OK")
        except Exception:
            update_log("   ✓ OK")

    def on_chunk_start(step: int, total: int) -> None:
        if step == 0:
            chunk_placeholder.info(f"📐 Étape {step + 1}/{total} — Création de la structure du cours...")
            status_placeholder.info("⏳ Génération en cours par étapes pour respecter les limites de l'API...")
        else:
            chunk_placeholder.info(f"📝 Étape {step + 1}/{total} — Génération du module {step}/{total - 1}...")

    try:
        final_message = run_agent_chunked(
            content=content,
            course_title=course_title,
            level=level,
            num_modules=num_modules,
            num_lessons=num_lessons,
            extra_instructions=extra_instructions,
            on_text=on_text,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_chunk_start=on_chunk_start,
            publish_to_notion=publish_notion,
        )

        chunk_placeholder.empty()
        status_placeholder.success("✅ Cours créé avec succès !")

        if final_message:
            st.divider()
            st.subheader("Résumé")
            st.markdown(final_message)

        st.divider()
        col_quiz, col_fc = st.columns(2)
        with col_quiz:
            if st.button("➡️ Faire le quiz", type="primary", use_container_width=True):
                st.switch_page("app.py")
        with col_fc:
            if st.button("🃏 Étudier les flashcards", use_container_width=True):
                st.switch_page("app.py")

    except RuntimeError as e:
        chunk_placeholder.empty()
        status_placeholder.error(str(e))
    except Exception as e:
        chunk_placeholder.empty()
        status_placeholder.error(f"Une erreur s'est produite : {e}")
        update_log(f"\n✗ **Erreur :** {e}")


def _display_generation(agent_fn) -> None:
    """Affiche la progression pour le mode sujet libre."""
    st.divider()
    st.subheader("Progression")

    log_lines: list[str] = []
    status_placeholder = st.empty()
    log_placeholder = st.empty()

    def update_log(line: str) -> None:
        log_lines.append(line)
        log_placeholder.markdown("\n".join(log_lines))

    def on_text(text: str) -> None:
        update_log(f"\n💬 {text}")

    def on_tool_call(name: str, args: dict) -> None:
        icons = {
            "manage_curriculum": "📚",
            "manage_flashcards": "🃏",
            "manage_quiz": "❓",
            "manage_notion_page": "📄",
        }
        icon = icons.get(name, "🔧")
        action = args.get("action", "")
        label = args.get("title") or args.get("lesson_id") or args.get("course_id") or ""
        update_log(f"{icon} `{name}` → **{action}**{f' — *{label}*' if label else ''}")

    def on_tool_result(name: str, result: str) -> None:
        try:
            data = json.loads(result)
            if "error" in data:
                update_log(f"   ✗ `{data['error']}`")
            elif "id" in data:
                update_log(f"   ✓ id={data['id']}")
            elif "created" in data:
                update_log(f"   ✓ {data['created']} éléments créés")
            elif "pages_created" in data:
                update_log(f"   ✓ {data['pages_created']} pages publiées sur Notion")
            else:
                update_log("   ✓ OK")
        except Exception:
            update_log("   ✓ OK")

    status_placeholder.info("⏳ Génération en cours... (30 à 90 secondes selon la taille du cours)")

    try:
        final_message = agent_fn(on_text, on_tool_call, on_tool_result)

        status_placeholder.success("✅ Cours créé avec succès !")

        if final_message:
            st.divider()
            st.subheader("Résumé")
            st.markdown(final_message)

        st.divider()
        col_quiz, col_fc = st.columns(2)
        with col_quiz:
            if st.button("➡️ Faire le quiz", type="primary", use_container_width=True):
                st.switch_page("app.py")
        with col_fc:
            if st.button("🃏 Étudier les flashcards", use_container_width=True):
                st.switch_page("app.py")

    except RuntimeError as e:
        status_placeholder.error(str(e))
    except Exception as e:
        status_placeholder.error(f"Une erreur s'est produite : {e}")
        update_log(f"\n✗ **Erreur :** {e}")


# ---------------------------------------------------------------------------
# Onglets
# ---------------------------------------------------------------------------
tab_subject, tab_content = st.tabs(["📝 Depuis un sujet", "📄 Depuis mon contenu"])


# ── Onglet 1 : sujet libre ──────────────────────────────────────────────────
with tab_subject:
    st.caption("Décrivez le cours souhaité, le contenu est généré automatiquement.")

    with st.form("form_subject"):
        col1, col2 = st.columns(2)

        with col1:
            subject = st.text_input(
                "Sujet *",
                placeholder="ex: Les bases de Python",
            )
            level = st.selectbox(
                "Niveau",
                options=["Débutant", "Intermédiaire", "Avancé"],
                key="level_subject",
            )

        with col2:
            num_modules = st.slider("Nombre de modules", min_value=1, max_value=5, value=2, key="mod_subject")
            num_lessons = st.slider("Leçons par module", min_value=1, max_value=4, value=2, key="les_subject")

        extra = st.text_area(
            "Instructions supplémentaires (optionnel)",
            placeholder="ex: public lycéen, exemples concrets, focus sur la pratique...",
            height=80,
            key="extra_subject",
        )

        publish_notion_s = st.checkbox(
            "Publier sur Notion après génération",
            value=False,
            disabled=not settings.notion_api_key,
            key="notion_subject",
        )

        submitted_subject = st.form_submit_button("🚀 Lancer", type="primary", use_container_width=True)

    if submitted_subject:
        if not subject.strip():
            st.warning("Veuillez renseigner le sujet du cours.")
            st.stop()

        user_message = (
            f"Crée un cours complet sur : {subject.strip()}.\n"
            f"Niveau : {level} ({level_map[level]}).\n"
            f"Structure : {num_modules} module(s), {num_lessons} leçon(s) par module.\n"
            f"Pour chaque leçon, génère les flashcards et les questions de quiz.\n"
        )
        if extra.strip():
            user_message += f"Instructions supplémentaires : {extra.strip()}\n"

        run_generation(user_message, publish_notion_s)


# ── Onglet 2 : contenu personnel ────────────────────────────────────────────
with tab_content:
    st.caption("Collez votre contenu ou uploadez un PDF. L'app structure le cours et génère les flashcards et quiz.")

    col1, col2 = st.columns(2)
    with col1:
        course_title = st.text_input(
            "Titre du cours *",
            placeholder="ex: Cours de thermodynamique",
            key="course_title_content",
        )
        level_c = st.selectbox(
            "Niveau",
            options=["Débutant", "Intermédiaire", "Avancé"],
            key="level_content",
        )
    with col2:
        num_modules_c = st.slider("Nombre de modules", min_value=1, max_value=5, value=2, key="mod_content")
        num_lessons_c = st.slider("Leçons par module", min_value=1, max_value=4, value=2, key="les_content")

    input_method = st.radio(
        "Comment fournir le contenu ?",
        options=["Coller du texte", "Uploader un PDF"],
        horizontal=True,
        key="input_method_content",
    )

    pasted_text = ""
    uploaded_pdf = None

    if input_method == "Coller du texte":
        pasted_text = st.text_area(
            "Contenu du cours *",
            placeholder="Collez ici vos notes, slides, ou tout autre contenu...",
            height=300,
            key="pasted_text_content",
        )
    else:
        uploaded_pdf = st.file_uploader(
            "Fichier PDF *",
            type=["pdf"],
            key="pdf_uploader_content",
        )

    extra_c = st.text_area(
        "Instructions supplémentaires (optionnel)",
        placeholder="ex: insiste sur les formules, ajoute des exemples pratiques...",
        height=80,
        key="extra_content",
    )

    publish_notion_c = st.checkbox(
        "Publier sur Notion après génération",
        value=False,
        disabled=not settings.notion_api_key,
        key="notion_content",
    )

    launch_content = st.button("🚀 Lancer", type="primary", use_container_width=True, key="launch_content")

    if launch_content:
        if not course_title.strip():
            st.warning("Veuillez renseigner le titre du cours.")
            st.stop()

        # ── Récupération du contenu brut ─────────────────────────────────────
        raw_content = ""
        if input_method == "Coller du texte":
            if not pasted_text.strip():
                st.warning("Veuillez coller du contenu.")
                st.stop()
            raw_content = pasted_text.strip()
        else:
            if uploaded_pdf is None:
                st.warning("Veuillez uploader un fichier PDF.")
                st.stop()
            with st.spinner("Extraction du texte PDF..."):
                raw_content = extract_pdf_text(uploaded_pdf)
            if not raw_content:
                st.error("Impossible d'extraire du texte de ce PDF.")
                st.stop()

        # ── Choix du mode : direct ou chunked ────────────────────────────────
        if len(raw_content) > CHUNK_THRESHOLD:
            # Contenu trop grand → mode chunked (1 appel API par module)
            nb_chars = len(raw_content)
            st.info(
                f"📄 Contenu détecté : **{nb_chars:,} caractères**. "
                f"Génération en **{num_modules_c + 1} étapes** pour respecter les limites de l'API "
                f"(~1 minute d'attente entre chaque étape)."
            )
            run_generation_chunked(
                content=raw_content,
                course_title=course_title.strip(),
                level=level_map[level_c],
                num_modules=num_modules_c,
                num_lessons=num_lessons_c,
                extra_instructions=extra_c.strip(),
                publish_notion=publish_notion_c,
            )
        else:
            # Contenu court → mode direct (un seul appel)
            user_message = (
                f"Crée un cours structuré intitulé : \"{course_title.strip()}\".\n"
                f"Niveau : {level_c} ({level_map[level_c]}).\n"
                f"Structure : {num_modules_c} module(s), {num_lessons_c} leçon(s) par module.\n"
                f"Base-toi UNIQUEMENT sur le contenu fourni ci-dessous pour rédiger les leçons, "
                f"les flashcards et les questions de quiz. "
                f"Ne complète pas avec des informations externes.\n"
            )
            if extra_c.strip():
                user_message += f"Instructions supplémentaires : {extra_c.strip()}\n"
            user_message += f"\n--- CONTENU ---\n{raw_content}\n--- FIN DU CONTENU ---"

            run_generation(user_message, publish_notion_c)