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

st.set_page_config(page_title="Quiz Results", page_icon="📊", layout="wide")

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

# Summary header
overall_pct = round(total_score / total_max * 100, 1) if total_max > 0 else 0
overall_passed = lessons_passed == len(attempts)

summary_col1, summary_col2, summary_col3 = st.columns(3)
summary_col1.metric("Overall Score", f"{total_score:.1f} / {total_max:.1f}")
summary_col2.metric("Percentage", f"{overall_pct}%")
summary_col3.metric(
    "Lessons Passed",
    f"{lessons_passed} / {len(attempts)}",
    delta="Pass" if overall_passed else "Fail",
    delta_color="normal" if overall_passed else "inverse",
)

st.divider()

# ---------------------------------------------------------------------------
# Per-lesson breakdown
# ---------------------------------------------------------------------------
retry_questions: dict[int, list[dict]] = {}  # lesson_id → wrong questions

for item in lesson_results:
    block = item["block"]
    lesson_title = block["lesson_title"]
    module_title = block.get("module_title", "")

    if "error" in item:
        st.error(f"Could not load results for '{lesson_title}': {item['error']}")
        continue

    result = item["result"]
    pct = result.get("percentage", 0)
    passed = result.get("passed", False)

    # Lesson header with badge
    badge = "✅ PASSED" if passed else "❌ FAILED"
    badge_color = "green" if passed else "red"
    st.markdown(
        f"### {lesson_title}  "
        f"<span style='color:{badge_color};font-size:0.8em'>{badge}</span>",
        unsafe_allow_html=True,
    )
    if module_title:
        st.caption(f"{block.get('course_title','')} › {module_title}")

    score_col, pct_col = st.columns([1, 3])
    score_col.metric(
        "Score",
        f"{result.get('score', 0):.1f} / {result.get('max_score', 0):.1f}",
    )
    pct_col.progress(int(pct), text=f"{pct}%")

    # Per-question table
    wrong_for_retry: list[dict] = []
    for q in result.get("questions", []):
        is_correct = q.get("is_correct", False)
        icon = "✓" if is_correct else "✗"
        color = "green" if is_correct else "red"

        user_ans = q.get("user_answer", [])
        correct_ans = q.get("correct_answer")

        # Format answers for display
        if isinstance(user_ans, list):
            user_display = ", ".join(user_ans) if user_ans else "—"
        else:
            user_display = str(user_ans) if user_ans else "—"

        if isinstance(correct_ans, list):
            correct_display = ", ".join(correct_ans)
        else:
            correct_display = str(correct_ans) if correct_ans else "—"

        st.markdown(
            f"<span style='color:{color}'>{icon}</span> **Q{q['question_index']+1}.** "
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
