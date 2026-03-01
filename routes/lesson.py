from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from services.database import get_db
from sqlalchemy.orm import Session
from models.Learn.content_model import Topic, Subtopic, SubtopicSummary, Content
from schemas.Learn.learn_schema import LessonResponse, SubtopicOut, ContentOut, SubtopicSummaryOut
from routes.auth import require_user

router = APIRouter(dependencies=[Depends(require_user)])

@router.get("/{topic_id}", response_model=LessonResponse)
async def get_lesson(topic_id: int, db: Session = Depends(get_db)):
    print(
        f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /lesson/{topic_id} called",
        flush=True,
    )
    topic = db.query(Topic).filter(Topic.topic_id == topic_id).first()
    if not topic:
        print(
            f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /lesson/{topic_id} topic not found",
            flush=True,
        )
        raise HTTPException(status_code=404, detail="Topic not found")

    subtopics = (
        db.query(Subtopic)
        .filter(Subtopic.topic_id == topic_id)
        .order_by(Subtopic.subtopic_id.asc())
        .all()
    )

    subtopic_ids = [subtopic.subtopic_id for subtopic in subtopics]
    print(
        f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /lesson/{topic_id} subtopics={len(subtopic_ids)}",
        flush=True,
    )

    contents_by_subtopic = {}
    if subtopic_ids:
        all_contents = (
            db.query(Content)
            .filter(Content.subtopic_id.in_(subtopic_ids))
            .order_by(Content.content_id.asc())
            .all()
        )
        print(
            f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /lesson/{topic_id} contents={len(all_contents)}",
            flush=True,
        )
        for content in all_contents:
            contents_by_subtopic.setdefault(content.subtopic_id, []).append(content)

    published_summaries_by_subtopic = {}
    if subtopic_ids:
        summaries = (
            db.query(SubtopicSummary)
            .filter(
                SubtopicSummary.topic_id == topic_id,
                SubtopicSummary.subtopic_id.in_(subtopic_ids),
                SubtopicSummary.is_published.is_(True),
            )
            .order_by(SubtopicSummary.summary_id.desc())
            .all()
        )
        print(
            f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /lesson/{topic_id} published_summaries={len(summaries)}",
            flush=True,
        )
        for summary in summaries:
            # Keep the latest published summary per subtopic.
            if summary.subtopic_id not in published_summaries_by_subtopic:
                published_summaries_by_subtopic[summary.subtopic_id] = summary

    subtopic_items = []
    for subtopic in subtopics:
        contents = [
            ContentOut(
                content_id=content.content_id,
                subtopic_id=content.subtopic_id,
                difficulty=content.difficulty,
                title=content.title,
                summary=content.summary,
                content_json=content.content_json,
            )
            for content in contents_by_subtopic.get(subtopic.subtopic_id, [])
        ]

        summary = published_summaries_by_subtopic.get(subtopic.subtopic_id)
        summary_out = None
        if summary:
            summary_out = SubtopicSummaryOut(
                summary_id=summary.summary_id,
                topic_id=summary.topic_id,
                subtopic_id=summary.subtopic_id,
                summary_content=summary.summary_content,
                is_published=summary.is_published,
            )

        subtopic_items.append(
            SubtopicOut(
                subtopic_id=subtopic.subtopic_id,
                topic_id=subtopic.topic_id,
                subtopic_name=subtopic.subtopic_name,
                contents=contents,
                subtopic_summary=summary_out,
            )
        )

    response = LessonResponse(
        topic_id=topic.topic_id,
        topic_name=topic.topic_name,
        subtopics=subtopic_items,
    )
    print(
        f"[DEBUG] {datetime.now(timezone.utc).isoformat()} GET /lesson/{topic_id} completed subtopics_returned={len(subtopic_items)}",
        flush=True,
    )
    return response
