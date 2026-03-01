from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, JSON, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from services.database import Base

class SubtopicProgressUser(Base):
    __tablename__ = "subtopic_progress_user"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.topic_id"), nullable=False)
    subtopic_id = Column(Integer, ForeignKey("subtopics.subtopic_id"), nullable=False)

    starting_difficulty = Column(String, CheckConstraint("starting_difficulty IN ('basic','core','mastery')"))
    current_difficulty = Column(String, CheckConstraint("current_difficulty IN ('basic','core','mastery')"))
    stage = Column(String, CheckConstraint(
        "stage IN ('profiling','content','quiz','explanation','summary','completed')"), nullable=False)
    is_completed = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ProfilingResults(Base):
    __tablename__ = "profiling_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.topic_id"), nullable=False)
    subtopic_id = Column(Integer, ForeignKey("subtopics.subtopic_id"), nullable=False)

    basic_score = Column(Integer, nullable=False)
    core_score = Column(Integer, nullable=False)
    mastery_score = Column(Integer, nullable=False)
    assigned_difficulty = Column(String, CheckConstraint("assigned_difficulty IN ('basic','core','mastery')"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class QuizAttempts(Base):
    __tablename__ = "quiz_attempts"

    quiz_attempt_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.topic_id"), nullable=False)
    subtopic_id = Column(Integer, ForeignKey("subtopics.subtopic_id"), nullable=False)
    difficulty = Column(String, CheckConstraint("difficulty IN ('basic','core','mastery')"), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    total_questions = Column(Integer, nullable=False)
    correct_count = Column(Integer, nullable=False)
    passed = Column(Boolean, nullable=False)
    points_awarded = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class QuizAttemptQuestions(Base):
    __tablename__ = "quiz_attempt_questions"

    quiz_attempt_id = Column(UUID(as_uuid=True), ForeignKey("quiz_attempts.quiz_attempt_id", ondelete="CASCADE"), primary_key=True)
    question_id = Column(Integer, primary_key=True)
    question_source = Column(String, CheckConstraint("question_source IN ('standard','llm')"), nullable=False)
    is_correct = Column(Boolean, nullable=False)

class LLMGeneratedQuestions(Base):
    __tablename__ = "llm_generated_questions"

    llm_question_id = Column(Integer, primary_key=True, autoincrement=True)
    topic_id = Column(Integer, ForeignKey("topics.topic_id"), nullable=False)
    subtopic_id = Column(Integer, ForeignKey("subtopics.subtopic_id"), nullable=False)
    difficulty = Column(String, CheckConstraint("difficulty IN ('basic','core','mastery')"), nullable=False)
    question_hash = Column(String, nullable=False, unique=True)
    content_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
