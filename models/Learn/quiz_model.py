from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from services.database import Base


class Quiz(Base):
    __tablename__ = "questions"
    question_id = Column(Integer, primary_key=True, index=True)
    subtopic_id = Column(Integer, ForeignKey("subtopics.subtopic_id"), nullable=False)
    difficulty = Column(String(50), nullable=False)
    question_type = Column(Text, nullable=False)
    content_json = Column(JSONB, nullable=False)
    is_published = Column(Boolean, nullable=False)