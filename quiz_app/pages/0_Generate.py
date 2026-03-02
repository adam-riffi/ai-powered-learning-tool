"""Course generation page.

User pastes text or uploads a PDF.
The app structures the course and generates flashcards + quiz from that content.
The number of modules and lessons is determined automatically by the model.

Location: quiz_app/pages/0_Generate.py
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

st.set_page_config(page_title="Create a course", layout="wide")
st.title("Create a course")

if not settings.groq_api_key:
    st.error(
        "**GROQ_API_KEY missing.**\n\n"
        "Add your key to the `.env` file:\n```\nGROQ_API_KEY=your_key_here\n```\n\n"
        "Free key available at [console.groq.com](https://console.groq.com)."
    )
    st.stop()

# 4000 chars ~ 1000 tokens, comfortable for the free tier (12k TPM)
CHUNK_THRESHOLD = 4000

level_map = {"Beginner": "beginner", "Intermediate": "intermediate", "Advanced": "advanced"}


def extract_pdf_text(uploaded_file) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(uploaded_file.read()))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()
    except ImportError:
        st.error("pypdf is not installed. Run: `pip install pypdf`")
        st.stop()


def run_generation(user_message: str, publish_notion: bool) -> None:
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
    from agent import run_agent_chunked

    st.divider()
    st.subheader("Progress")

    total_steps = num_modules + 1
    log_lines: list[str] = []
    status_placeholder = st.empty()
    chunk_placeholder = st.empty()
    log_placeholder = st.empty()

    def update_log(line: str) -> None:
        log_lines.append(line)
        log_placeholder.markdown("\n".join(log_lines))

    def on_text(text: str) -> None:
        if "Pause" in text:
            return
        update_log(f"\n{text}")

    def on_tool_call(name: str, args: dict) -> None:
        action = args.get("action", "")
        label = args.get("title") or args.get("lesson_id") or args.get("course_id") or ""
        update_log(f"`{name}` -> **{action}**{f' — *{label}*' if label else ''}")

    def on_tool_result(name: str, result: str) -> None:
        try:
            data = json.loads(result)
            if "error" in data:
                update_log(f"   error `{data['error']}`")
            elif "id" in data:
                update_log(f"   ok id={data['id']}")
            elif "created" in data:
                update_log(f"   ok {data['created']} items created")
            elif "pages_created" in data:
                update_log(f"   ok {data['pages_created']} pages published to Notion")
            else:
                update_log("   ok")
        except Exception:
            update_log("   ok")

    def on_chunk_start(step: int, total: int) -> None:
        if step == 0:
            chunk_placeholder.info(f"Step {step + 1}/{total} — Creating course structure...")
            status_placeholder.info("Generation in progress...")
        else:
            chunk_placeholder.info(f"Step {step + 1}/{total} — Generating module {step}/{total - 1}...")

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
        status_placeholder.success("Course created successfully!")

        if final_message:
            st.divider()
            st.subheader("Summary")
            st.markdown(final_message)

        st.divider()
        col_quiz, col_fc = st.columns(2)
        with col_quiz:
            if st.button("Take the quiz", type="primary", use_container_width=True):
                st.switch_page("app.py")
        with col_fc:
            if st.button("Study flashcards", use_container_width=True):
                st.switch_page("app.py")

    except RuntimeError as e:
        chunk_placeholder.empty()
        status_placeholder.error(str(e))
    except Exception as e:
        chunk_placeholder.empty()
        status_placeholder.error(f"An error occurred: {e}")
        update_log(f"\nerror: {e}")


def _display_generation(agent_fn) -> None:
    st.divider()
    st.subheader("Progress")

    log_lines: list[str] = []
    status_placeholder = st.empty()
    log_placeholder = st.empty()

    def update_log(line: str) -> None:
        log_lines.append(line)
        log_placeholder.markdown("\n".join(log_lines))

    def on_text(text: str) -> None:
        update_log(f"\n{text}")

    def on_tool_call(name: str, args: dict) -> None:
        action = args.get("action", "")
        label = args.get("title") or args.get("lesson_id") or args.get("course_id") or ""
        update_log(f"`{name}` -> **{action}**{f' — *{label}*' if label else ''}")

    def on_tool_result(name: str, result: str) -> None:
        try:
            data = json.loads(result)
            if "error" in data:
                update_log(f"   error `{data['error']}`")
            elif "id" in data:
                update_log(f"   ok id={data['id']}")
            elif "created" in data:
                update_log(f"   ok {data['created']} items created")
            elif "pages_created" in data:
                update_log(f"   ok {data['pages_created']} pages published to Notion")
            else:
                update_log("   ok")
        except Exception:
            update_log("   ok")

    status_placeholder.info("Generation in progress... (30 to 90 seconds depending on course size)")

    try:
        final_message = agent_fn(on_text, on_tool_call, on_tool_result)
        status_placeholder.success("Course created successfully!")

        if final_message:
            st.divider()
            st.subheader("Summary")
            st.markdown(final_message)

        st.divider()
        col_quiz, col_fc = st.columns(2)
        with col_quiz:
            if st.button("Take the quiz", type="primary", use_container_width=True):
                st.switch_page("app.py")
        with col_fc:
            if st.button("Study flashcards", use_container_width=True):
                st.switch_page("app.py")

    except RuntimeError as e:
        status_placeholder.error(str(e))
    except Exception as e:
        status_placeholder.error(f"An error occurred: {e}")
        update_log(f"\nerror: {e}")


# --- Main form ---

st.caption("Paste your content or upload a PDF. The app structures the course and generates flashcards and quiz.")

course_title = st.text_input(
    "Course title *",
    placeholder="e.g. Thermodynamics course",
    key="course_title_content",
)
level_c = st.selectbox(
    "Level",
    options=["Beginner", "Intermediate", "Advanced"],
    key="level_content",
)
input_method = st.radio(
    "How to provide content?",
    options=["Paste text", "Upload PDF"],
    horizontal=True,
    key="input_method_content",
)

pasted_text = ""
uploaded_pdf = None

if input_method == "Paste text":
    pasted_text = st.text_area(
        "Course content *",
        placeholder="Paste your notes, slides, or any other content here...",
        height=300,
        key="pasted_text_content",
    )
else:
    uploaded_pdf = st.file_uploader("PDF file *", type=["pdf"], key="pdf_uploader_content")

extra_c = st.text_area(
    "Additional instructions (optional)",
    placeholder="e.g. focus on formulas, add practical examples...",
    height=80,
    key="extra_content",
)
publish_notion_c = st.checkbox(
    "Publish to Notion after generation",
    value=False,
    disabled=not settings.notion_api_key,
    key="notion_content",
)
launch_content = st.button("Launch", type="primary", use_container_width=True, key="launch_content")

if launch_content:
    if not course_title.strip():
        st.warning("Please enter a course title.")
        st.stop()

    raw_content = ""
    if input_method == "Paste text":
        if not pasted_text.strip():
            st.warning("Please paste some content.")
            st.stop()
        raw_content = pasted_text.strip()
    else:
        if uploaded_pdf is None:
            st.warning("Please upload a PDF file.")
            st.stop()
        with st.spinner("Extracting PDF text..."):
            raw_content = extract_pdf_text(uploaded_pdf)
        if not raw_content:
            st.error("Could not extract text from this PDF.")
            st.stop()

    if len(raw_content) > CHUNK_THRESHOLD:
        nb_chars = len(raw_content)
        auto_modules = max(2, min(5, nb_chars // 3000))
        auto_lessons = 2
        st.info(
            f"Content detected: **{nb_chars:,} characters**. "
            f"Generation in **{auto_modules + 1} steps** to respect API limits "
            f"(~1 minute wait between each step)."
        )
        run_generation_chunked(
            content=raw_content,
            course_title=course_title.strip(),
            level=level_map[level_c],
            num_modules=auto_modules,
            num_lessons=auto_lessons,
            extra_instructions=extra_c.strip(),
            publish_notion=publish_notion_c,
        )
    else:
        user_message = (
            f"Create a structured course titled: \"{course_title.strip()}\".\n"
            f"Level: {level_c} ({level_map[level_c]}).\n"
            f"Analyse the provided content and determine yourself the optimal number of modules and lessons "
            f"based on the quantity and nature of the content. "
            f"Base yourself ONLY on the content provided below for lessons, flashcards and quiz questions. "
            f"Do not supplement with external information.\n"
        )
        if extra_c.strip():
            user_message += f"Additional instructions: {extra_c.strip()}\n"
        user_message += f"\n--- CONTENT ---\n{raw_content}\n--- END CONTENT ---"

        run_generation(user_message, publish_notion_c)