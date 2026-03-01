from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Any
from datetime import datetime
from uuid import UUID


class SubtopicProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    topic_id: int
    subtopic_id: int
    starting_difficulty: Optional[str]
    current_difficulty: Optional[str]
    stage: str
    is_completed: bool
    created_at: datetime
    updated_at: datetime

class ProfilingResultsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    topic_id: int
    subtopic_id: int
    basic_score: int
    core_score: int
    mastery_score: int
    assigned_difficulty: str
    created_at: datetime

class QuizAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quiz_attempt_id: UUID
    user_id: UUID
    topic_id: int
    subtopic_id: int
    difficulty: str
    attempt_number: int
    total_questions: int
    correct_count: int
    passed: bool
    points_awarded: int
    created_at: datetime

class QuizAttemptQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    quiz_attempt_id: UUID
    question_id: int
    question_source: str
    is_correct: bool

class LLMGeneratedQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    llm_question_id: int
    topic_id: int
    subtopic_id: int
    difficulty: str
    question_hash: str
    content_json: Any
    explanation: Optional[str] = None
    correct_answer: Optional[str] = None
    created_at: datetime
