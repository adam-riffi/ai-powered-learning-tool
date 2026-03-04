"""Results page.

Shows per-lesson score cards with:
- Pass / Fail badge
- Per-question breakdown (user answer vs correct, ✓ / ✗)
- Overall summary
- Retry Failed Questions button
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import streamlit as st
from tools.quiz_tool import manage_quiz
from auth_guard import require_auth, render_sidebar_user

st.set_page_config(page_title="Quiz Results", page_icon="📊", layout="wide")

require_auth()
render_sidebar_user()

# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------
if "quiz_attempts" not in st.session_state or not st.session_state["quiz_attempts"]:
    st.warning("No quiz results to display.")
    if st.button("← Back to Setup"):
        st.switch_page("app.py")
    st.stop()

attempts: list[dict] = st.session_state["quiz_attempts"]

st.title("📊 Quiz Results")
st.divider()

# ---------------------------------------------------------------------------
# Aggregate stats
# ---------------------------------------------------------------------------
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

summary_col1, summary_col2, summary_col3 = st.columns(3)
summary_col1.metric("Overall Score", f"{total_score:.1f} / {total_max:.1f}")
summary_col2.metric("Pass Rate", f"{overall_pct}%")
summary_col3.metric("Lessons Passed", f"{lessons_passed} / {len(attempts)}")

if overall_passed:
    st.success("All lessons passed!")
else:
    st.warning(f"{len(attempts) - lessons_passed} lesson(s) below the passing threshold (70%).")

st.divider()

# ---------------------------------------------------------------------------
# Per-lesson breakdown
# ---------------------------------------------------------------------------
retry_questions: dict[int, list[dict]] = {}

for item in lesson_results:
    block = item["block"]
    lesson_title = block["lesson_title"]

    if "error" in item:
        st.error(f"**{lesson_title}**: Could not load results — {item['error']}")
        continue

    result = item["result"]
    passed = result.get("passed", False)
    score = result.get("score", 0)
    max_score = result.get("max_score", 0)
    pct = round(score / max_score * 100, 1) if max_score else 0

    badge = "✅ Pass" if passed else "❌ Fail"
    with st.expander(f"{badge} — {lesson_title} ({pct}%)", expanded=not passed):
        q_col1, q_col2 = st.columns(2)
        q_col1.metric("Score", f"{score:.1f} / {max_score:.1f}")
        q_col2.metric("Result", "Pass" if passed else "Fail")

        breakdown = result.get("breakdown", [])
        wrong_for_retry = []

        for q in breakdown:
            is_correct = q.get("is_correct", False)
            icon = "✓" if is_correct else "✗"
            color = "green" if is_correct else "red"
            user_answer = q.get("user_answer", [])
            correct_answer = q.get("correct_answer", [])

            user_display = ", ".join(user_answer) if isinstance(user_answer, list) else str(user_answer)
            correct_display = ", ".join(correct_answer) if isinstance(correct_answer, list) else str(correct_answer)

            st.markdown(
                f"<span style='color:{color}'>{icon}</span> "
                f"**Q{q.get('question_index', 0) + 1}.** "
                f"{q.get('question', '')}",
                unsafe_allow_html=True,
            )

            detail_col1, detail_col2 = st.columns(2)
            detail_col1.markdown(f"Your answer: `{user_display}`")
            detail_col2.markdown(f"Correct: `{correct_display}`")

            if not is_correct:
                wrong_for_retry.append(q)

            st.write("")

        if wrong_for_retry:
            retry_questions[block["lesson_id"]] = wrong_for_retry

    st.divider()

# ---------------------------------------------------------------------------
# Retry failed questions
# ---------------------------------------------------------------------------
if retry_questions:
    st.subheader("Try Again?")
    st.caption(
        f"You got {sum(len(v) for v in retry_questions.values())} question(s) wrong "
        "across the quiz. Retry those only?"
    )

    if st.button("🔁 Retry Failed Questions", type="secondary"):
        from database import get_db
        from models import QuizAttempt

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
if st.button("← New Quiz", use_container_width=True):
    st.session_state.pop("quiz_attempts", None)
    st.session_state.pop("quiz_answers", None)
    st.switch_page("app.py")