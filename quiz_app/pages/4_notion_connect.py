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
# Fonctions de publication (définies avant leur usage)
# ---------------------------------------------------------------------------

def _do_publish(courses: list):
    """Publie les cours sélectionnés en utilisant le token de session."""
    import tools.notion_tool as nt
    from notion_client import Client
    from config import settings

    token = st.session_state["notion_token"]
    root_page_id = st.session_state.get("notion_root_page_id", "")

    # Remplacement temporaire du client Notion par celui de l'utilisateur
    _original_get_client = nt._get_notion_client

    def _session_client():
        return Client(auth=token)

    nt._get_notion_client = _session_client

    # Injection temporaire de la page racine
    _original_root = settings.notion_root_page_id
    settings.notion_root_page_id = root_page_id or None

    try:
        for course in courses:
            with st.spinner(f"Publication de \u00ab {course['title']} \u00bb..."):
                try:
                    from tools.notion_tool import manage_notion_page
                    result = manage_notion_page(
                        action="publish_course",
                        course_id=course["id"],
                    )
                    st.success(
                        f"\u2705 **{course['title']}** publi\u00e9 \u2014 "
                        f"{result['pages_created']} pages cr\u00e9\u00e9es sur Notion."
                    )
                except Exception as e:
                    st.error(f"\u274c Erreur pour \u00ab {course['title']} \u00bb : {e}")
    finally:
        nt._get_notion_client = _original_get_client
        settings.notion_root_page_id = _original_root


def _publish_section():
    """Affiche les cours disponibles et permet de les publier sur Notion."""
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
        st.info("Aucun cours en base de donn\u00e9es. Cr\u00e9ez-en un depuis la page **Cr\u00e9er un cours**.")
        return

    not_synced = [c for c in course_list if not c["notion_page_id"]]
    already_synced = [c for c in course_list if c["notion_page_id"]]

    if already_synced:
        st.info(
            "D\u00e9j\u00e0 publi\u00e9s sur Notion : "
            + ", ".join(f"**{c['title']}**" for c in already_synced)
            + ". Republier cr\u00e9erait des doublons."
        )

    if not not_synced:
        st.success("Tous vos cours sont d\u00e9j\u00e0 publi\u00e9s sur Notion \U0001f389")
        return

    st.markdown("**Cours non encore publi\u00e9s :**")
    to_publish = st.multiselect(
        "S\u00e9lectionnez les cours \u00e0 publier",
        options=[c["title"] for c in not_synced],
        default=[c["title"] for c in not_synced],
    )

    if st.button("\U0001f4e4 Publier sur Notion", type="primary", disabled=not to_publish):
        selected = [c for c in not_synced if c["title"] in to_publish]
        _do_publish(selected)


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Connexion Notion", page_icon="\U0001f4c4", layout="centered")

st.title("\U0001f4c4 Connexion \u00e0 Notion")
st.caption(
    "Connectez votre compte Notion pour publier vos cours automatiquement. "
    "Votre token n'est jamais stock\u00e9 sur nos serveurs \u2014 il reste dans votre session navigateur."
)

# ---------------------------------------------------------------------------
# Statut actuel
# ---------------------------------------------------------------------------
is_connected = bool(st.session_state.get("notion_token"))

if is_connected:
    st.success("\u2705 Vous \u00eates connect\u00e9 \u00e0 Notion pour cette session.")

    with st.expander("Infos de connexion"):
        token_val = st.session_state["notion_token"]
        masked = token_val[:10] + "..." + token_val[-4:]
        st.markdown(f"**Token :** `{masked}`")
        root = st.session_state.get("notion_root_page_id") or "*(racine du workspace)*"
        st.markdown(f"**Page racine :** `{root}`")

    if st.button("\U0001f50c Se d\u00e9connecter", type="secondary"):
        st.session_state.pop("notion_token", None)
        st.session_state.pop("notion_root_page_id", None)
        st.rerun()

    st.divider()
    st.subheader("Publier un cours existant")
    _publish_section()

else:
    # ---------------------------------------------------------------------------
    # Guide + formulaire de connexion
    # ---------------------------------------------------------------------------
    st.subheader("\u00c9tape 1 \u2014 Cr\u00e9er une int\u00e9gration Notion")

    with st.expander("\U0001f4d6 Comment obtenir mon token Notion ?", expanded=True):
        st.markdown("""
**1.** Allez sur [notion.so/my-integrations](https://www.notion.so/my-integrations)

**2.** Cliquez **"+ New integration"**, donnez-lui un nom (ex: *Learn AI*) et s\u00e9lectionnez votre workspace.

**3.** Copiez le **"Internal Integration Secret"** qui commence par `ntn_\u2026`

**4.** Sur la page Notion o\u00f9 vous voulez publier : cliquez **"\u2026"** en haut \u00e0 droite \u2192 **"Add connections"** \u2192 s\u00e9lectionnez votre int\u00e9gration.

**5.** Copiez l'ID de cette page depuis son URL :
`notion.so/Mon-Titre-`**`xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`**

> L'ID est la suite de 32 caract\u00e8res \u00e0 la fin de l'URL (sans les tirets).
        """)

    st.subheader("\u00c9tape 2 \u2014 Entrez vos informations")

    with st.form("notion_connect_form"):
        token_input = st.text_input(
            "Token d'int\u00e9gration *",
            type="password",
            placeholder="ntn_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            help="Commence par 'ntn_'. Trouvez-le sur notion.so/my-integrations",
        )

        root_input = st.text_input(
            "ID de la page racine (optionnel)",
            placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            help=(
                "L'ID est la partie finale de l'URL de votre page Notion. "
                "Si laiss\u00e9 vide, les cours seront cr\u00e9\u00e9s \u00e0 la racine du workspace."
            ),
        )

        submitted = st.form_submit_button(
            "\U0001f517 Connecter \u00e0 Notion",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        token_clean = token_input.strip()
        root_clean = root_input.strip()

        if not token_clean:
            st.error("Le token est requis.")
        elif not token_clean.startswith("ntn_"):
            st.warning("\u26a0\ufe0f Le token doit commencer par `ntn_`. V\u00e9rifiez votre copie.")
        else:
            with st.spinner("V\u00e9rification du token aupr\u00e8s de Notion..."):
                try:
                    from notion_client import Client
                    client = Client(auth=token_clean)
                    me = client.users.me()  # Appel de validation

                    st.session_state["notion_token"] = token_clean
                    st.session_state["notion_root_page_id"] = root_clean

                    name = me.get("name", "")
                    st.success(
                        f"\u2705 Connect\u00e9{f' en tant que **{name}**' if name else ''} !"
                    )
                    st.rerun()

                except Exception as e:
                    err = str(e).lower()
                    if "401" in err or "unauthorized" in err:
                        st.error(
                            "\u274c Token invalide ou r\u00e9voqu\u00e9. "
                            "V\u00e9rifiez votre int\u00e9gration sur notion.so/my-integrations."
                        )
                    elif "404" in err or "object_not_found" in err:
                        st.error(
                            "\u274c Page racine introuvable. "
                            "V\u00e9rifiez l'ID et que votre int\u00e9gration a bien acc\u00e8s \u00e0 cette page."
                        )
                    else:
                        st.error(f"\u274c Erreur inattendue : {e}")