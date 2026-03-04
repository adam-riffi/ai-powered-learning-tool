"""Results page.

Shows per-lesson score cards with:
- Pass / Fail status
- Per-question breakdown (user answer vs correct)
- Overall summary
- Retry failed questions button
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from database import get_db
from models import QuizAttempt
from tools.quiz_tool import manage_quiz
from auth_guard import require_auth, render_sidebar_user

st.set_page_config(page_title="Quiz Results", page_icon="📊", layout="wide")

require_auth()
render_sidebar_user()

if "quiz_attempts" not in st.session_state or not st.session_state["quiz_attempts"]:
    st.warning("No quiz results to display.")
    if st.button("Back to Setup"):
        st.switch_page("app.py")
    st.stop()

attempts: list[dict] = st.session_state["quiz_attempts"]

st.title("Quiz Results")
st.divider()

# Aggregate scores across all lessons
total_score = 0.0
total_max = 0.0
lessons_passed = 0
lesson_results: list[dict] = []

for lesson_block in attempts:
    attempt_id = lesson_block["attempt_id"]
    try:
        result = manage_quiz(action="results", attempt_id=attempt_id)
        lesson_results.append({"block": lesson_block, "result": result})
        total_score += result.get("score") or 0
        total_max += result.get("max_score") or 0
        if result.get("passed"):
            lessons_passed += 1
    except Exception as e:
        lesson_results.append({"block": lesson_block, "error": str(e)})

overall_pct = round(total_score / total_max * 100, 1) if total_max > 0 else 0
overall_passed = lessons_passed == len(attempts)

score_col, rate_col, passed_col = st.columns(3)
score_col.metric("Overall Score", f"{total_score:.1f} / {total_max:.1f}")
rate_col.metric("Pass Rate", f"{overall_pct}%")
passed_col.metric("Lessons Passed", f"{lessons_passed} / {len(attempts)}")

if overall_passed:
    st.success("All lessons passed!")
else:
    st.warning(f"{len(attempts) - lessons_passed} lesson(s) below the passing threshold (70%).")

st.divider()

# Per-lesson breakdown
retry_questions: dict[int, list] = {}

for entry in lesson_results:
    block = entry["block"]
    lesson_title = block["lesson_title"]
    module_title = block.get("module_title", "")
    course_title = block.get("course_title", "")

    if "error" in entry:
        st.error(f"{lesson_title}: {entry['error']}")
        continue

    result = entry["result"]
    passed = result.get("passed", False)
    score = result.get("score", 0)
    max_score = result.get("max_score", 0)
    pct = result.get("percentage", 0)

    with st.expander(f"{lesson_title} — {pct}% ({'Pass' if passed else 'Fail'})", expanded=True):
        if module_title or course_title:
            st.caption(f"{course_title} > {module_title}")
        st.write(f"Score: {score:.1f} / {max_score:.1f}")

        wrong_in_lesson = []
        for q_data in result.get("questions", []):
            is_correct = q_data["is_correct"]
            qtext = q_data["question"]
            user_ans = q_data["user_answer"]
            correct_ans = q_data["correct_answer"]
            status = "Correct" if is_correct else "Wrong"

            st.markdown(f"**{qtext}**")
            st.write(f"{status} — Your answer: {user_ans} | Correct: {correct_ans}")

            if not is_correct:
                wrong_in_lesson.append(q_data)

        if wrong_in_lesson:
            retry_questions[block["lesson_id"]] = wrong_in_lesson

if retry_questions:
    st.divider()
    st.caption(
        f"{sum(len(v) for v in retry_questions.values())} question(s) answered incorrectly. "
        "Retry those only?"
    )

    if st.button("Retry Failed Questions", type="secondary"):
        new_attempts: list[dict] = []

        with get_db() as db:
            for block in attempts:
                lesson_id = block["lesson_id"]
                wrong_qs = retry_questions.get(lesson_id)
                if not wrong_qs:
                    continue

                new_attempt = QuizAttempt(
                    lesson_id=lesson_id,
                    questions=wrong_qs,
                    max_score=float(10 * len(wrong_qs)),
                )
                db.add(new_attempt)
                db.flush()

                new_attempts.append({
                    "attempt_id": new_attempt.id,
                    "lesson_id": lesson_id,
                    "lesson_title": block["lesson_title"],
                    "module_title": block.get("module_title", ""),
                    "course_title": block.get("course_title", ""),
                    "num_questions": len(wrong_qs),
                })

        if new_attempts:
            st.session_state["quiz_attempts"] = new_attempts
            st.session_state["quiz_answers"] = {}
            st.switch_page("pages/1_Take_Quiz.py")

st.divider()
if st.button("New Quiz", use_container_width=True):
    st.session_state.pop("quiz_attempts", None)
    st.session_state.pop("quiz_answers", None)
    st.switch_page("app.py")