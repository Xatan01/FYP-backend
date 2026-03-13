from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from schemas.Learn.learn_schema import LessonResponse
from schemas.Learn.user_learn_schema import SubtopicProgressOut
from services.database import get_db
from services.Learn.lesson_service import LessonService
from routes.auth import require_user

router = APIRouter(dependencies=[Depends(require_user)])

@router.post("/progress/{topic_id}/{subtopic_id}/init", response_model=SubtopicProgressOut)
async def init_progress(
    topic_id: int,
    subtopic_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await LessonService.init_progress(db, user["sub"], topic_id, subtopic_id)


@router.get("/{topic_id}", response_model=LessonResponse)
async def get_lesson(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await LessonService.get_lesson(db, user["sub"], topic_id)
