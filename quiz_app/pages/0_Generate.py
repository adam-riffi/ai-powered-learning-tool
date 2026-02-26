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
# Bandeau Notion (token de session)
# ---------------------------------------------------------------------------
notion_connected = bool(st.session_state.get("notion_token"))

if notion_connected:
    token_val = st.session_state["notion_token"]
    masked = token_val[:10] + "..." + token_val[-4:]
    st.info(
        f"📄 Notion connecté (`{masked}`). "
        "Vous pouvez publier automatiquement après génération. "
        "Pour changer de compte, rendez-vous sur **Connexion Notion**."
    )
else:
    st.warning(
        "📄 Notion non connecté. Connectez-vous via la page **Connexion Notion** "
        "pour publier vos cours automatiquement."
    )

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
    """Lance la génération et affiche la progression."""
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

    # ── Injection du token Notion de session si disponible ──────────────────
    notion_token = st.session_state.get("notion_token")
    notion_root = st.session_state.get("notion_root_page_id", "")

    _cleanup_notion = None
    if publish_notion and notion_token:
        import tools.notion_tool as nt
        from notion_client import Client as NotionClient

        _original_client_fn = nt._get_notion_client
        _original_root = settings.notion_root_page_id

        def _session_client():
            return NotionClient(auth=notion_token)

        nt._get_notion_client = _session_client
        settings.notion_root_page_id = notion_root or None

        def _cleanup_notion():
            nt._get_notion_client = _original_client_fn
            settings.notion_root_page_id = _original_root

    try:
        from agent import run_agent

        final_message = run_agent(
            user_message=user_message,
            on_text=on_text,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            publish_to_notion=publish_notion and bool(notion_token),
        )

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
    finally:
        if _cleanup_notion:
            _cleanup_notion()


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
            "📄 Publier sur Notion après génération",
            value=notion_connected,
            disabled=not notion_connected,
            help="Connectez-vous d'abord via la page 'Connexion Notion'." if not notion_connected else None,
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

    with st.form("form_content"):
        col1, col2 = st.columns(2)

        with col1:
            course_title = st.text_input(
                "Titre du cours *",
                placeholder="ex: Cours de thermodynamique",
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
        )

        pasted_text = ""
        uploaded_pdf = None

        if input_method == "Coller du texte":
            pasted_text = st.text_area(
                "Contenu du cours *",
                placeholder="Collez ici vos notes, slides, ou tout autre contenu...",
                height=300,
            )
        else:
            uploaded_pdf = st.file_uploader(
                "Fichier PDF *",
                type=["pdf"],
            )

        extra_c = st.text_area(
            "Instructions supplémentaires (optionnel)",
            placeholder="ex: insiste sur les formules, ajoute des exemples pratiques...",
            height=80,
            key="extra_content",
        )

        publish_notion_c = st.checkbox(
            "📄 Publier sur Notion après génération",
            value=notion_connected,
            disabled=not notion_connected,
            help="Connectez-vous d'abord via la page 'Connexion Notion'." if not notion_connected else None,
            key="notion_content",
        )

        submitted_content = st.form_submit_button("🚀 Lancer", type="primary", use_container_width=True)

    if submitted_content:
        if not course_title.strip():
            st.warning("Veuillez renseigner le titre du cours.")
            st.stop()

        # Récupération du contenu
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

        # Limiter à 12 000 caractères pour ne pas dépasser le contexte
        if len(raw_content) > 12000:
            raw_content = raw_content[:12000]
            st.info("Le contenu a été tronqué à 12 000 caractères pour la génération.")

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