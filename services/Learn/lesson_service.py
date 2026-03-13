from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from models.Learn.content_model import Content, Subtopic, SubtopicSummary, Topic
from models.Learn.user_learn_model import SubtopicProgressUser
from schemas.Learn.learn_schema import LessonResponse, SubtopicOut, ContentOut, SubtopicSummaryOut
from datetime import datetime, timezone
from services.Learn.progress_service import ProgressService

class LessonService:

    @staticmethod
    async def init_progress(db: AsyncSession, user_id: str, topic_id: int, subtopic_id: int):
        subtopic = (
            await db.execute(
                select(Subtopic).where(Subtopic.subtopic_id == subtopic_id)
            )
        ).scalar_one_or_none()
        if not subtopic:
            raise HTTPException(status_code=404, detail="Subtopic not found")
        if subtopic.topic_id != topic_id:
            raise HTTPException(
                status_code=400,
                detail="Subtopic does not belong to topic",
            )

        progress = (
            await db.execute(
                select(SubtopicProgressUser).where(
                    SubtopicProgressUser.user_id == user_id,
                    SubtopicProgressUser.subtopic_id == subtopic_id,
                )
            )
        ).scalar_one_or_none()
        if progress:
            return progress

        await ProgressService.ensure_subtopic_can_unlock(
            db, user_id, topic_id, subtopic_id
        )

        progress = SubtopicProgressUser(
            user_id=user_id,
            topic_id=topic_id,
            subtopic_id=subtopic_id,
            stage="profiling",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(progress)
        await db.commit()
        await db.refresh(progress)
        return progress

    @staticmethod
    async def get_lesson(db: AsyncSession, user_id: str, topic_id: int) -> LessonResponse:
        topic = (await db.execute(select(Topic).where(Topic.topic_id == topic_id))).scalar_one_or_none()
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

        subtopics, state_by_subtopic = await ProgressService.get_topic_unlock_state(
            db, user_id, topic_id
        )
        subtopic_ids = [s.subtopic_id for s in subtopics]

        # Fetch contents
        contents = []
        if subtopic_ids:
            contents = (
                await db.execute(
                    select(Content)
                    .where(Content.subtopic_id.in_(subtopic_ids))
                    .order_by(Content.content_id.asc())
                )
            ).scalars().all()
        contents_by_subtopic = {}
        for content in contents:
            contents_by_subtopic.setdefault(content.subtopic_id, []).append(content)

        # Fetch latest published summaries
        summaries = []
        if subtopic_ids:
            summaries = (
                await db.execute(
                    select(SubtopicSummary)
                    .where(
                        SubtopicSummary.topic_id == topic_id,
                        SubtopicSummary.subtopic_id.in_(subtopic_ids),
                        SubtopicSummary.is_published.is_(True),
                    )
                    .order_by(SubtopicSummary.summary_id.desc())
                )
            ).scalars().all()
        summaries_by_subtopic = {}
        for summary in summaries:
            if summary.subtopic_id not in summaries_by_subtopic:
                summaries_by_subtopic[summary.subtopic_id] = summary

        subtopic_items = []
        for s in subtopics:
            state = state_by_subtopic.get(s.subtopic_id, {})
            is_unlocked = bool(state.get("is_unlocked"))
            contents_list = [
                ContentOut(
                    content_id=c.content_id,
                    subtopic_id=c.subtopic_id,
                    difficulty=c.difficulty,
                    title=c.title,
                    summary=c.summary,
                    content_json=c.content_json,
                ) for c in contents_by_subtopic.get(s.subtopic_id, [])
            ] if is_unlocked else []
            summary_obj = summaries_by_subtopic.get(s.subtopic_id) if is_unlocked else None
            summary_out = SubtopicSummaryOut(
                summary_id=summary_obj.summary_id,
                topic_id=summary_obj.topic_id,
                subtopic_id=summary_obj.subtopic_id,
                summary_content=summary_obj.summary_content,
                is_published=summary_obj.is_published
            ) if summary_obj else None

            subtopic_items.append(
                SubtopicOut(
                    subtopic_id=s.subtopic_id,
                    topic_id=s.topic_id,
                    subtopic_name=s.subtopic_name,
                    is_unlocked=is_unlocked,
                    can_unlock=bool(state.get("can_unlock")),
                    requires_profiling=bool(state.get("requires_profiling", True)),
                    stage=state.get("stage"),
                    is_completed=bool(state.get("is_completed")),
                    contents=contents_list,
                    subtopic_summary=summary_out,
                )
            )

        return LessonResponse(topic_id=topic.topic_id, topic_name=topic.topic_name, subtopics=subtopic_items)
