"""SQLAlchemy ORM models.

Relational structure (mirrors a Notion-style workspace):
    Course  (= a Notion database)
      └── Module  (= a view / category)
            └── Lesson  (= a database page)
                  ├── Flashcard  (child records, not synced to Notion)
                  └── QuizAttempt  (child records, not synced to Notion)
"""
import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON, Boolean, DateTime, Enum as SAEnum, Float,
    ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CourseLevel(str, enum.Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class CourseStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    PUBLISHED = "published"


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------

class Course(Base):
    """Top-level learning programme — analogous to a Notion database."""
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[CourseLevel] = mapped_column(SAEnum(CourseLevel), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    hours_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[CourseStatus] = mapped_column(
        SAEnum(CourseStatus), default=CourseStatus.DRAFT, nullable=False
    )

    # Notion sync metadata
    notion_page_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notion_database_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    modules: Mapped[List["Module"]] = relationship(
        "Module", back_populates="course", cascade="all, delete-orphan",
        order_by="Module.order_index"
    )


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class Module(Base):
    """Groups of related lessons inside a course."""
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notion_page_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    course: Mapped["Course"] = relationship("Course", back_populates="modules")
    lessons: Mapped[List["Lesson"]] = relationship(
        "Lesson", back_populates="module", cascade="all, delete-orphan",
        order_by="Lesson.order_index"
    )


# ---------------------------------------------------------------------------
# Lesson
# ---------------------------------------------------------------------------

class Lesson(Base):
    """Individual learning unit — analogous to a page in a Notion database."""
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Markdown
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)    # e.g. ["python", "loops"]
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notion_page_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    module: Mapped["Module"] = relationship("Module", back_populates="lessons")
    flashcards: Mapped[List["Flashcard"]] = relationship(
        "Flashcard", back_populates="lesson", cascade="all, delete-orphan"
    )
    quiz_attempts: Mapped[List["QuizAttempt"]] = relationship(
        "QuizAttempt", back_populates="lesson", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Flashcard
# ---------------------------------------------------------------------------

class Flashcard(Base):
    """Front/back flashcard linked to a lesson. NOT synced to Notion.

    The agent populates `front` and `back` freely — no schema constraints
    on the content. `tags` mirrors the lesson's tag vocabulary for filtering.
    """
    __tablename__ = "flashcards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    lesson: Mapped["Lesson"] = relationship("Lesson", back_populates="flashcards")


# ---------------------------------------------------------------------------
# QuizAttempt
# ---------------------------------------------------------------------------

class QuizAttempt(Base):
    """A single quiz session for a lesson.

    `questions` JSON schema (each item):
        {
            "question": "What is X?",
            "options": ["A", "B", "C", "D"],
            "correct_answer": "B",        # single-answer: str
            "correct_answers": ["A","C"], # multi-select: list[str] (use one or the other)
            "type": "single" | "multi"
        }

    `answers` JSON schema (each item):
        {
            "question_index": 0,
            "selected": ["B"]   # always a list, even for single-answer
        }

    `weak_areas`: list of question indices the user answered incorrectly.
    """
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), nullable=False)

    questions: Mapped[list] = mapped_column(JSON, nullable=False)
    answers: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    weak_areas: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    lesson: Mapped["Lesson"] = relationship("Lesson", back_populates="quiz_attempts")
