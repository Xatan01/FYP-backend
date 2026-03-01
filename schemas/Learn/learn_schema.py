from pydantic import BaseModel
from typing import Any, Dict, List, Optional

class ContentOut(BaseModel):
    content_id: int
    subtopic_id: int
    difficulty: str
    title: str
    summary: Optional[str] = None
    content_json: Dict[str, Any]


class SubtopicSummaryOut(BaseModel):
    summary_id: int
    topic_id: int
    subtopic_id: int
    summary_content: Dict[str, Any]
    is_published: bool


class SubtopicOut(BaseModel):
    subtopic_id: int
    topic_id: int
    subtopic_name: str
    contents: List[ContentOut]
    subtopic_summary: Optional[SubtopicSummaryOut] = None


class LessonResponse(BaseModel):
    topic_id: int
    topic_name: str
    subtopics: List[SubtopicOut]
