from fastapi import HTTPException
from models.Learn.content_model import SubtopicSummary
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

class ProgressService:

    @staticmethod
    async def get_subtopic_summary(db: AsyncSession, subtopic_id: int):
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
        return summary
