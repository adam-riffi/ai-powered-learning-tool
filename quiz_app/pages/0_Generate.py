"""Page de génération de cours.

Permet à l'utilisateur de décrire un cours et de suivre
sa création en temps réel.

Placement : quiz_app/pages/0_Generate.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import streamlit as st
from database import init_db
from config import settings

init_db()

st.set_page_config(page_title="Générer un cours", page_icon="✨", layout="wide")

st.title("✨ Créer un cours")
st.caption("Décrivez le cours souhaité. Les leçons, flashcards et questions sont générés automatiquement.")

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
# Formulaire
# ---------------------------------------------------------------------------
with st.form("generation_form"):
    st.subheader("Paramètres du cours")

    col1, col2 = st.columns(2)

    with col1:
        subject = st.text_input(
            "Sujet *",
            placeholder="ex: Les bases de Python",
        )
        level = st.selectbox(
            "Niveau",
            options=["Débutant", "Intermédiaire", "Avancé"],
        )

    with col2:
        num_modules = st.slider("Nombre de modules", min_value=1, max_value=5, value=2)
        num_lessons = st.slider("Leçons par module", min_value=1, max_value=4, value=2)

    extra = st.text_area(
        "Instructions supplémentaires (optionnel)",
        placeholder="ex: public lycéen, exemples concrets, focus sur la pratique...",
        height=80,
    )

    notion_col, _ = st.columns([1, 2])
    with notion_col:
        publish_notion = st.checkbox(
            "Publier sur Notion après génération",
            value=False,
            disabled=not settings.notion_api_key,
            help="Nécessite NOTION_API_KEY et NOTION_ROOT_PAGE_ID dans .env"
            if not settings.notion_api_key
            else None,
        )

    submitted = st.form_submit_button("🚀 Lancer", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------
if submitted:
    if not subject.strip():
        st.warning("Veuillez renseigner le sujet du cours.")
        st.stop()

    level_map = {"Débutant": "beginner", "Intermédiaire": "intermediate", "Avancé": "advanced"}
    level_en = level_map[level]

    user_message = (
        f"Crée un cours complet sur : {subject.strip()}.\n"
        f"Niveau : {level} ({level_en}).\n"
        f"Structure : {num_modules} module(s), {num_lessons} leçon(s) par module.\n"
        f"Pour chaque leçon, génère les flashcards et les questions de quiz.\n"
    )
    if extra.strip():
        user_message += f"Instructions supplémentaires : {extra.strip()}\n"

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
        from agent import run_agent

        final_message = run_agent(
            user_message=user_message,
            on_text=on_text,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            publish_to_notion=publish_notion,
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