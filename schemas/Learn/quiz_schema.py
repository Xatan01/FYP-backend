from pydantic import BaseModel
from typing import Any, Dict

class QuestionOut(BaseModel):
    question_id: int
    subtopic_id: int
    question_type: str
    title: str
    question_json: Dict[str, Any]
    is_published: bool

