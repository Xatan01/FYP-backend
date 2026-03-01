from pydantic import BaseModel
from typing import Any, Dict

class QuestionOut(BaseModel):
    question_id: int
    subtopic_id: int
    question_type: str
    title: str
    question_json: Dict[str, Any]
    is_published: bool


class QuizSubmitResultOut(BaseModel):
    attempt_number: int
    passed: bool
    total_correct: int
    points_awarded: int
    required_correct: int
    total_questions: int


class ExplanationItemOut(BaseModel):
    question_id: int
    source: str
    is_correct: bool

