from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.Learn.content_model import Subtopic, SubtopicSummary
from models.Learn.user_learn_model import SubtopicProgressUser

class ProgressService:

    @staticmethod
    def _is_completed(progress: SubtopicProgressUser | None) -> bool:
        return bool(progress and (progress.is_completed or progress.stage in {"summary", "completed"}))

    @staticmethod
    def _is_unlocked(progress: SubtopicProgressUser | None) -> bool:
        return bool(progress and progress.stage != "profiling")

    @staticmethod
    async def get_topic_unlock_state(
        db: AsyncSession,
        user_id: str,
        topic_id: int,
    ) -> tuple[list[Subtopic], dict[int, dict]]:
        subtopics = (
            await db.execute(
                select(Subtopic)
                .where(Subtopic.topic_id == topic_id)
                .order_by(Subtopic.subtopic_id.asc())
            )
        ).scalars().all()

        progress_rows = (
            await db.execute(
                select(SubtopicProgressUser).where(
                    SubtopicProgressUser.user_id == user_id,
                    SubtopicProgressUser.topic_id == topic_id,
                )
            )
        ).scalars().all()
        progress_by_subtopic = {
            progress.subtopic_id: progress for progress in progress_rows
        }

        state_by_subtopic: dict[int, dict] = {}
        previous_completed = True
        for index, subtopic in enumerate(subtopics):
            progress = progress_by_subtopic.get(subtopic.subtopic_id)
            can_unlock = bool(index == 0 or previous_completed)
            is_unlocked = bool(can_unlock and ProgressService._is_unlocked(progress))
            is_completed = ProgressService._is_completed(progress)
            state_by_subtopic[subtopic.subtopic_id] = {
                "progress": progress,
                "is_unlocked": is_unlocked,
                "can_unlock": can_unlock,
                "requires_profiling": bool(can_unlock and not is_unlocked),
                "stage": progress.stage if progress else None,
                "is_completed": is_completed,
            }
            previous_completed = is_completed

        return subtopics, state_by_subtopic

    @staticmethod
    async def ensure_subtopic_can_unlock(
        db: AsyncSession,
        user_id: str,
        topic_id: int,
        subtopic_id: int,
    ) -> None:
        _, state_by_subtopic = await ProgressService.get_topic_unlock_state(
            db, user_id, topic_id
        )
        state = state_by_subtopic.get(subtopic_id)
        if not state or not state["can_unlock"]:
            raise HTTPException(
                status_code=403,
                detail="Subtopic is locked until the previous subtopic is completed",
            )

    @staticmethod
    async def ensure_subtopic_is_unlocked(
        db: AsyncSession,
        user_id: str,
        topic_id: int,
        subtopic_id: int,
    ) -> None:
        _, state_by_subtopic = await ProgressService.get_topic_unlock_state(
            db, user_id, topic_id
        )
        state = state_by_subtopic.get(subtopic_id)
        if not state or not state["is_unlocked"]:
            raise HTTPException(
                status_code=403,
                detail="Subtopic is locked until profiling and the previous completion requirements are met",
            )

    @staticmethod
    async def get_subtopic_summary(
        db: AsyncSession,
        subtopic_id: int,
        user_id: str | None = None,
    ):
        """
        Fetch the latest published summary for a subtopic asynchronously.
        """
        result = await db.execute(
            select(SubtopicSummary)
            .where(
                SubtopicSummary.subtopic_id == subtopic_id,
                SubtopicSummary.is_published.is_(True)
            )
            .order_by(SubtopicSummary.summary_id.desc())
        )
        summary = result.scalars().first()
        if not summary:
            raise HTTPException(status_code=404, detail="Summary not found")

        if user_id is not None:
            progress = (
                await db.execute(
                    select(SubtopicProgressUser).where(
                        SubtopicProgressUser.user_id == user_id,
                        SubtopicProgressUser.subtopic_id == subtopic_id,
                    )
                )
            ).scalar_one_or_none()
            if not progress:
                raise HTTPException(status_code=409, detail="Progress not initialized")
            if progress.stage not in {"explanation", "summary", "completed"}:
                raise HTTPException(
                    status_code=409,
                    detail="Summary not available at this stage",
                )

            progress.stage = "completed"
            progress.is_completed = True
            progress.updated_at = datetime.now(timezone.utc)
            await db.commit()

        return summary
