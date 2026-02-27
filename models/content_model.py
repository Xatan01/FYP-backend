from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from services.database import Base

class Topic(Base):
    __tablename__ = "topics"
    topic_id = Column(Integer, primary_key=True, index=True)
    topic_name = Column(Text, unique=True, index=True, nullable=False)

class Subtopic(Base):
    __tablename__ = "subtopics"
    subtopic_id = Column(Integer, primary_key=True, index=True)
    subtopic_name = Column(Text, unique=True, index=True, nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.topic_id"), nullable=False)

class SubtopicSummary(Base):
    __tablename__ = "subtopic_summary"
    summary_id = Column(Integer, primary_key=True, index=True)
    topic_id = Column(Integer, ForeignKey("topics.topic_id"), nullable=False)
    subtopic_id = Column(Integer, ForeignKey("subtopics.subtopic_id"), nullable=False)
    summary_content = Column(JSONB, nullable=False)
    is_published = Column(Boolean, default=False)

class Content(Base):
    __tablename__ = "content"
    content_id = Column(Integer, primary_key=True, index=True)
    subtopic_id = Column(Integer, ForeignKey("subtopics.subtopic_id"), nullable=False)
    difficulty = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=True)
    content_json = Column(JSONB, nullable=False)
