"""Take Quiz page.

Displays questions grouped by lesson.
- Single answer  -> radio buttons
- Multi-select   -> checkboxes

Users work through each lesson block and submit all at once.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from tools.quiz_tool import manage_quiz
from auth_guard import require_auth, render_sidebar_user

st.set_page_config(page_title="Take Quiz", page_icon="🧠", layout="wide")

require_auth()
render_sidebar_user()

if "quiz_attempts" not in st.session_state or not st.session_state["quiz_attempts"]:
    st.warning("No active quiz. Please start a quiz from the home page.")
    if st.button("Back to Setup"):
        st.switch_page("app.py")
    st.stop()

attempts: list[dict] = st.session_state["quiz_attempts"]
answers_store: dict = st.session_state.setdefault("quiz_answers", {})

# Store question counts per attempt to avoid re-fetching on submit
if "quiz_question_counts" not in st.session_state:
    st.session_state["quiz_question_counts"] = {}
question_counts: dict = st.session_state["quiz_question_counts"]

st.title("Take Quiz")
st.caption(
    f"Answering {len(attempts)} lesson(s). "
    "Complete all sections, then hit Submit All at the bottom."
)
st.divider()

# Render questions per lesson block
for lesson_block in attempts:
    attempt_id = lesson_block["attempt_id"]
    lesson_title = lesson_block["lesson_title"]
    module_title = lesson_block.get("module_title", "")
    course_title = lesson_block.get("course_title", "")

    attempt_data = manage_quiz(action="get", attempt_id=attempt_id)
    questions = attempt_data.get("questions", [])

    # Cache the question count so we don't need another DB call on submit
    question_counts[attempt_id] = len(questions)

    if not questions:
        st.info(f"No questions for lesson '{lesson_title}'.")
        continue

    st.subheader(lesson_title)
    if module_title or course_title:
        st.caption(f"{course_title} > {module_title}")

    lesson_answers: dict[int, list[str]] = {}

    for idx, question in enumerate(questions):
        qtext = question.get("question", f"Question {idx + 1}")
        options: list[str] = question.get("options", [])
        qtype = question.get("type", "single")

        st.markdown(f"**Q{idx + 1}. {qtext}**")
        key = f"attempt_{attempt_id}_q{idx}"

        if not options:
            st.warning("This question has no options — skipping.")
            lesson_answers[idx] = []
            continue

        if qtype == "single":
            chosen = st.radio(
                label=f"Select one answer for Q{idx + 1}",
                options=options,
                index=None,
                key=key,
                label_visibility="collapsed",
            )
            lesson_answers[idx] = [chosen] if chosen else []
        else:
            st.caption("Select all that apply:")
            chosen_multi: list[str] = []
            for opt in options:
                opt_key = f"{key}_opt_{opt}"
                if st.checkbox(opt, key=opt_key):
                    chosen_multi.append(opt)
            lesson_answers[idx] = chosen_multi

        st.write("")

    answers_store[attempt_id] = lesson_answers
    st.divider()

# Submit all answers
st.subheader("Ready?")

if st.button("Submit All Answers", type="primary", use_container_width=True):
    all_submitted = True
    submission_errors: list[str] = []

    for lesson_block in attempts:
        attempt_id = lesson_block["attempt_id"]
        lesson_answers = answers_store.get(attempt_id, {})
        num_questions = question_counts.get(attempt_id, 0)

        unanswered = [
            i for i in range(num_questions)
            if not lesson_answers.get(i)
        ]

        if unanswered:
            submission_errors.append(
                f"Lesson '{lesson_block['lesson_title']}': "
                f"{len(unanswered)} unanswered question(s) "
                f"(Q{[u + 1 for u in unanswered]})."
            )
            all_submitted = False
            continue

        answers_payload = [
            {"question_index": q_idx, "selected": selected}
            for q_idx, selected in lesson_answers.items()
        ]

        try:
            manage_quiz(action="submit", attempt_id=attempt_id, answers=answers_payload)
        except Exception as e:
            submission_errors.append(
                f"Error submitting '{lesson_block['lesson_title']}': {e}"
            )
            all_submitted = False

    if submission_errors:
        for err in submission_errors:
            st.warning(err)

    if all_submitted:
        st.success("All answers submitted! Loading results...")
        st.switch_page("pages/2_Results.py")
    else:
        st.info("Fix the warnings above, then resubmit.")