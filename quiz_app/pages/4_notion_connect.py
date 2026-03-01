"""Page de connexion Notion.

Permet à l'utilisateur de renseigner son token Notion et sa page racine
directement dans l'interface, sans toucher au fichier .env.

Le token est stocké dans st.session_state["notion_token"] et
st.session_state["notion_root_page_id"] pour la durée de la session.

Placement : quiz_app/pages/4_Notion_Connect.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st


# ---------------------------------------------------------------------------
# Fonction de publication
# ---------------------------------------------------------------------------

def _do_publish(courses: list):
    """Publie les cours sélectionnés en utilisant le token de session."""
    from tools.notion_tool import manage_notion_page

    token = st.session_state["notion_token"]
    root_page_id = st.session_state.get("notion_root_page_id") or None

    for course in courses:
        action_label = "Republication" if course["notion_page_id"] else "Publication"
        with st.spinner(f"{action_label} de « {course['title']} »..."):
            try:
                result = manage_notion_page(
                    action="publish_course",
                    course_id=course["id"],
                    api_key=token,
                    root_page_id=root_page_id,
                )
                st.success(
                    f"✅ **{course['title']}** publié — "
                    f"{result['pages_created']} pages créées sur Notion."
                )
            except Exception as e:
                st.error(f"❌ Erreur pour « {course['title']} » : {e}")


def _publish_section():
    """Affiche tous les cours et permet de les publier / republier."""
    from database import get_db
    from models import Course
    from sqlalchemy import select

    with get_db() as db:
        courses = db.scalars(select(Course).order_by(Course.title)).all()
        course_list = [
            {
                "id": c.id,
                "title": c.title,
                "notion_page_id": c.notion_page_id,
            }
            for c in courses
        ]

    if not course_list:
        st.info("Aucun cours en base de données. Créez-en un depuis la page **Créer un cours**.")
        return

    # Affiche un badge pour les cours déjà publiés
    already_synced = [c for c in course_list if c["notion_page_id"]]
    if already_synced:
        titles = ", ".join(f"**{c['title']}**" for c in already_synced)
        st.info(
            f"Déjà publiés : {titles}. "
            "Les republier remplacera automatiquement les pages existantes sur Notion."
        )

    selected_titles = st.multiselect(
        "Sélectionnez les cours à publier / republier",
        options=[c["title"] for c in course_list],
        default=[c["title"] for c in course_list],
    )

    if st.button("📤 Publier sur Notion", type="primary", disabled=not selected_titles):
        selected = [c for c in course_list if c["title"] in selected_titles]
        _do_publish(selected)


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Connexion Notion", page_icon="📄", layout="centered")

st.title("📄 Connexion à Notion")
st.caption(
    "Connectez votre compte Notion pour publier vos cours automatiquement. "
    "Votre token n'est jamais stocké sur nos serveurs — il reste dans votre session navigateur."
)

# ---------------------------------------------------------------------------
# Statut actuel
# ---------------------------------------------------------------------------
is_connected = bool(st.session_state.get("notion_token"))

if is_connected:
    token_val = st.session_state["notion_token"]
    masked = token_val[:10] + "..." + token_val[-4:]
    st.success(f"✅ Connecté à Notion — `{masked}`")

    with st.expander("Infos de connexion"):
        st.markdown(f"**Token :** `{masked}`")
        root = st.session_state.get("notion_root_page_id") or "*(racine du workspace)*"
        st.markdown(f"**Page racine :** `{root}`")

    if st.button("🔌 Se déconnecter", type="secondary"):
        st.session_state.pop("notion_token", None)
        st.session_state.pop("notion_root_page_id", None)
        st.rerun()

    st.divider()
    st.subheader("Publier un cours sur Notion")
    _publish_section()

else:
    # ---------------------------------------------------------------------------
    # Guide + formulaire de connexion
    # ---------------------------------------------------------------------------
    st.subheader("Étape 1 — Créer une intégration Notion")

    with st.expander("📖 Comment obtenir mon token Notion ?", expanded=True):
        st.markdown("""
**1.** Allez sur [notion.so/my-integrations](https://www.notion.so/my-integrations)

**2.** Cliquez **"+ New integration"**, donnez-lui un nom (ex: *Learn AI*) et sélectionnez votre workspace.

**3.** Copiez le **"Internal Integration Secret"** qui commence par `ntn_`

**4.** Sur la page Notion où vous voulez publier : cliquez **"…"** en haut à droite → **"Add connections"** → sélectionnez votre intégration.

**5.** Copiez l'ID de cette page depuis son URL :
`notion.so/Mon-Titre-`**`xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`**

> L'ID est la suite de 32 caractères à la fin de l'URL (sans les tirets).
        """)

    st.subheader("Étape 2 — Entrez vos informations")

    with st.form("notion_connect_form"):
        token_input = st.text_input(
            "Token d'intégration *",
            type="password",
            placeholder="ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            help="Commence par 'ntn_'. Trouvez-le sur notion.so/my-integrations",
        )

        root_input = st.text_input(
            "ID de la page racine (optionnel)",
            placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            help=(
                "L'ID est la partie finale de l'URL de votre page Notion. "
                "Si laissé vide, les cours seront créés à la racine du workspace."
            ),
        )

        submitted = st.form_submit_button(
            "🔗 Connecter à Notion",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        token_clean = token_input.strip()
        root_clean = root_input.strip()

        if not token_clean:
            st.error("Le token est requis.")
        elif not (token_clean.startswith("ntn_") or token_clean.startswith("secret_")):
            st.warning("⚠️ Le token doit commencer par `ntn_` ou `secret_`. Vérifiez votre copie.")
        else:
            with st.spinner("Vérification du token auprès de Notion..."):
                try:
                    from notion_client import Client
                    client = Client(auth=token_clean)
                    me = client.users.me()

                    st.session_state["notion_token"] = token_clean
                    st.session_state["notion_root_page_id"] = root_clean

                    name = me.get("name", "")
                    st.success(f"✅ Connecté{f' en tant que **{name}**' if name else ''} !")
                    st.rerun()

                except Exception as e:
                    err = str(e).lower()
                    if "401" in err or "unauthorized" in err:
                        st.error(
                            "❌ Token invalide ou révoqué. "
                            "Vérifiez votre intégration sur notion.so/my-integrations."
                        )
                    elif "404" in err or "object_not_found" in err:
                        st.error(
                            "❌ Page racine introuvable. "
                            "Vérifiez l'ID et que votre intégration a bien accès à cette page."
                        )
                    else:
                        st.error(f"❌ Erreur inattendue : {e}")