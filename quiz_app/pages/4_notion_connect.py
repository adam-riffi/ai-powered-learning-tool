"""Notion connection page.

Allows the user to enter their Notion token and root page ID
directly in the interface, without touching the .env file.

The token is stored in st.session_state["notion_token"] and
st.session_state["notion_root_page_id"] for the duration of the session.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select
import streamlit as st

from auth_guard import render_sidebar_user, require_auth
from database import get_db
from models import Course
from tools.notion_tool import manage_notion_page


def _do_publish(courses: list) -> None:
    token = st.session_state["notion_token"]
    root_page_id = st.session_state.get("notion_root_page_id") or None

    for course in courses:
        action_label = "Republishing" if course["notion_page_id"] else "Publishing"
        with st.spinner(f"{action_label} '{course['title']}'..."):
            try:
                result = manage_notion_page(
                    action="publish_course",
                    course_id=course["id"],
                    api_key=token,
                    root_page_id=root_page_id,
                )
                st.success(
                    f"**{course['title']}** published — "
                    f"{result['pages_created']} pages created on Notion."
                )
            except Exception as e:
                st.error(f"Error for '{course['title']}': {e}")


def _publish_section() -> None:
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
        st.info("No courses in the database. Create one from the **Create a course** page.")
        return

    already_synced = [c for c in course_list if c["notion_page_id"]]
    if already_synced:
        titles = ", ".join(f"**{c['title']}**" for c in already_synced)
        st.info(
            f"Already published: {titles}. "
            "Republishing will automatically replace the existing Notion pages."
        )

    selected_titles = st.multiselect(
        "Select courses to publish / republish",
        options=[c["title"] for c in course_list],
        default=[c["title"] for c in course_list],
    )

    if st.button("Publish to Notion", type="primary", disabled=not selected_titles):
        selected = [c for c in course_list if c["title"] in selected_titles]
        _do_publish(selected)


st.set_page_config(page_title="Notion Connection", layout="centered")

require_auth()
render_sidebar_user()

st.title("Notion Connection")
st.caption(
    "Connect your Notion account to publish courses automatically. "
    "Your token is never stored on our servers — it stays in your browser session."
)

is_connected = bool(st.session_state.get("notion_token"))

if is_connected:
    token_val = st.session_state["notion_token"]
    masked = token_val[:10] + "..." + token_val[-4:]
    root = st.session_state.get("notion_root_page_id") or "*(workspace root)*"

    st.success(f"Connected to Notion — `{masked}`")

    with st.expander("Connection details"):
        st.markdown(f"**Token:** `{masked}`")
        st.markdown(f"**Root page:** `{root}`")

    if st.button("Disconnect", type="secondary"):
        st.session_state.pop("notion_token", None)
        st.session_state.pop("notion_root_page_id", None)
        st.rerun()

    st.divider()
    st.subheader("Publish a course to Notion")
    _publish_section()

else:
    st.subheader("Step 1 — Create a Notion integration")

    with st.expander("How to get my Notion token?", expanded=True):
        st.markdown("""
**1.** Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)

**2.** Click **"+ New integration"**, give it a name (e.g. *Learn AI*) and select your workspace.

**3.** Copy the **"Internal Integration Secret"** — it starts with `ntn_`

**4.** In Notion, create an empty page where your courses will be published (e.g. *"Learn AI"*).
On that page, click **"…"** in the top-right → **"Add connections"** → select your integration.

**5.** Copy the page ID from its URL:
`notion.so/My-Title-`**`xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`**

> The ID is the 32-character string at the end of the URL (without dashes).
>
> **This field is required.**
""")

    st.subheader("Step 2 — Enter your credentials")

    token_input = st.text_input(
        "Notion Integration Token *",
        type="password",
        placeholder="ntn_...",
    )
    root_input = st.text_input(
        "Root Page ID *",
        placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    )

    if st.button("Connect", type="primary", disabled=not token_input or not root_input):
        st.session_state["notion_token"] = token_input.strip()
        st.session_state["notion_root_page_id"] = root_input.strip()
        st.success("Connected! You can now publish courses to Notion.")
        st.rerun()
