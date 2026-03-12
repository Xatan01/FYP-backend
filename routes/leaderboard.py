from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.leaderboard_schema import LeaderboardsOut
from services.database import get_db
from services.leaderboard_service import LeaderboardService

router = APIRouter(tags=["leaderboard"])


@router.get("", response_model=LeaderboardsOut)
async def get_leaderboards(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await LeaderboardService.get_leaderboards(db, me_user_id=user["sub"])
