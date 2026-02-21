"""Quiz App — Home / Quiz Setup Page.

Run with:
    streamlit run quiz_app/app.py

This page lets users:
1. Select courses
2. Pick specific lessons
3. Choose number of questions per lesson and question type filter
4. Start the quiz — which stores attempts and navigates to Take_Quiz
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from database import init_db, get_db
from models import Course, Module, Lesson, QuizAttempt
from sqlalchemy import select

# Ensure tables exist
init_db()

st.set_page_config(page_title="Learn AI", page_icon="🎓", layout="wide")

st.title("🎓 Learning Assistant")
st.caption("Select lessons, then start a quiz or study flashcards.")

# ---------------------------------------------------------------------------
# Load all courses
# ---------------------------------------------------------------------------
with get_db() as db:
    courses = db.scalars(select(Course).order_by(Course.title)).all()
    # Eagerly load relationships before session closes
    course_data = []
    for course in courses:
        modules_data = []
        for module in course.modules:
            lessons_data = []
            for lesson in module.lessons:
                has_quizzes = len(lesson.quiz_attempts) > 0
                has_flashcards = len(lesson.flashcards) > 0
                lesson_quiz_types = set()
                for attempt in lesson.quiz_attempts:
                    for q in (attempt.questions or []):
                        lesson_quiz_types.add(q.get("type", "single"))
                lessons_data.append({
                    "id": lesson.id,
                    "title": lesson.title,
                    "is_completed": lesson.is_completed,
                    "has_quizzes": has_quizzes,
                    "has_flashcards": has_flashcards,
                    "quiz_types": lesson_quiz_types,
                    "latest_attempt_id": (
                        lesson.quiz_attempts[0].id if lesson.quiz_attempts else None
                    ),
                })
            if lessons_data:
                modules_data.append({
                    "id": module.id,
                    "title": module.title,
                    "lessons": lessons_data,
                })
        if modules_data:
            course_data.append({
                "id": course.id,
                "title": course.title,
                "topic": course.topic,
                "modules": modules_data,
            })

if not course_data:
    st.info(
        "No courses found in the database. "
        "The agent needs to create courses with lessons first."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Step 1: Select courses
# ---------------------------------------------------------------------------
st.subheader("Step 1: Select courses")
all_course_titles = {c["title"]: c for c in course_data}
selected_course_titles = st.multiselect(
    "Which courses do you want to study?",
    options=list(all_course_titles.keys()),
    default=[],
)

if not selected_course_titles:
    st.info("Select at least one course to continue.")
    st.stop()

selected_courses = [all_course_titles[t] for t in selected_course_titles]

# ---------------------------------------------------------------------------
# Step 2: Select lessons
# ---------------------------------------------------------------------------
st.subheader("Step 2: Select lessons")
all_lessons: list[dict] = []
for course in selected_courses:
    for module in course["modules"]:
        for lesson in module["lessons"]:
            all_lessons.append({
                **lesson,
                "course_title": course["title"],
                "module_title": module["title"],
                "label": f"{course['title']} › {module['title']} › {lesson['title']}",
            })

lesson_labels = [l["label"] for l in all_lessons]
lesson_by_label = {l["label"]: l for l in all_lessons}

selected_labels = st.multiselect(
    "Select lessons to include",
    options=lesson_labels,
    default=lesson_labels,  # all selected by default
)

if not selected_labels:
    st.info("Select at least one lesson.")
    st.stop()

selected_lessons = [lesson_by_label[label] for label in selected_labels]

# Availability hints
has_any_quiz = any(l.get("has_quizzes") for l in selected_lessons)
has_any_fc   = any(l.get("has_flashcards") for l in selected_lessons)

# ---------------------------------------------------------------------------
# Step 3: Quiz settings
# ---------------------------------------------------------------------------
st.subheader("Step 3: Quiz settings")

col1, col2 = st.columns(2)

with col1:
    # Check how many questions exist across selected lessons
    max_questions = 20
    questions_per_lesson = st.slider(
        "Questions per lesson",
        min_value=1,
        max_value=max_questions,
        value=5,
        help="The quiz will pick up to this many questions from each lesson's stored questions.",
    )

with col2:
    question_type_filter = st.selectbox(
        "Question type",
        options=["All", "Single-answer only", "Multi-select only"],
        help="Filter questions by type.",
    )

type_map = {
    "All": None,
    "Single-answer only": "single",
    "Multi-select only": "multi",
}
selected_type = type_map[question_type_filter]

# ---------------------------------------------------------------------------
# Step 4: Choose mode
# ---------------------------------------------------------------------------
st.divider()

quiz_col, fc_col = st.columns(2)

# ── Flashcards ──────────────────────────────────────────────────────────────
with fc_col:
    fc_disabled = not has_any_fc
    fc_help = None if has_any_fc else "None of the selected lessons have flashcards yet."
    if st.button(
        "🃏 Study Flashcards",
        type="secondary",
        use_container_width=True,
        disabled=fc_disabled,
        help=fc_help,
    ):
        fc_lessons = [
            {
                "lesson_id": l["id"],
                "lesson_title": l["title"],
                "module_title": l["module_title"],
                "course_title": l["course_title"],
            }
            for l in selected_lessons
            if l.get("has_flashcards")
        ]
        st.session_state["flashcard_lessons"] = fc_lessons
        # Clear stale deck caches so the new selection loads fresh
        for key in list(st.session_state.keys()):
            if key.startswith("fc_deck_"):
                del st.session_state[key]
        st.session_state["fc_index"] = 0
        st.session_state["fc_revealed"] = False
        st.switch_page("pages/3_Flashcards.py")

# ── Quiz ────────────────────────────────────────────────────────────────────
with quiz_col:
    quiz_disabled = not has_any_quiz
    quiz_help = None if has_any_quiz else "None of the selected lessons have quiz questions yet."
    if st.button(
        "🚀 Start Quiz",
        type="primary",
        use_container_width=True,
        disabled=quiz_disabled,
        help=quiz_help,
    ):
        # For each selected lesson, find the latest attempt with questions
        # (or the only existing one) and create a new "session" attempt
        attempt_ids: list[dict] = []
        errors: list[str] = []

        with get_db() as db:
            for lesson_info in selected_lessons:
                lesson = db.get(Lesson, lesson_info["id"])
                if not lesson:
                    errors.append(f"Lesson '{lesson_info['title']}' not found.")
                    continue

                # Gather all questions from all previous attempts for this lesson
                all_questions: list[dict] = []
                for attempt in lesson.quiz_attempts:
                    all_questions.extend(attempt.questions or [])

                if not all_questions:
                    errors.append(
                        f"Lesson '{lesson_info['title']}' has no quiz questions. "
                        "Ask the agent to create quiz questions for it first."
                    )
                    continue

                # Apply type filter
                if selected_type:
                    filtered = [
                        q for q in all_questions
                        if q.get("type", "single") == selected_type
                    ]
                else:
                    filtered = all_questions

                if not filtered:
                    errors.append(
                        f"No '{question_type_filter}' questions found for '{lesson_info['title']}'."
                    )
                    continue

                # Deduplicate by question text and limit
                seen: set[str] = set()
                unique_questions: list[dict] = []
                for q in filtered:
                    qtext = q.get("question", "")
                    if qtext not in seen:
                        seen.add(qtext)
                        unique_questions.append(q)

                questions_to_use = unique_questions[:questions_per_lesson]
                max_score = float(10 * len(questions_to_use))

                new_attempt = QuizAttempt(
                    lesson_id=lesson_info["id"],
                    questions=questions_to_use,
                    max_score=max_score,
                )
                db.add(new_attempt)
                db.flush()

                attempt_ids.append({
                    "attempt_id": new_attempt.id,
                    "lesson_id": lesson_info["id"],
                    "lesson_title": lesson_info["title"],
                    "module_title": lesson_info["module_title"],
                    "course_title": lesson_info["course_title"],
                    "num_questions": len(questions_to_use),
                })

        if errors:
            for err in errors:
                st.warning(err)

        if attempt_ids:
            st.session_state["quiz_attempts"] = attempt_ids
            st.session_state["quiz_current_lesson_idx"] = 0
            st.session_state["quiz_answers"] = {}  # attempt_id → list of answer dicts
            st.success(
                f"Quiz started! {len(attempt_ids)} lesson(s), "
                f"up to {questions_per_lesson} question(s) each."
            )
            st.switch_page("pages/1_Take_Quiz.py")
        elif not errors:
            st.error("No valid lessons with questions found for the selected configuration.")
