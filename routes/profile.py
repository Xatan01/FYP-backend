from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.profile_schema import (
    ProfileGameSummaryOut,
    ProfileSettingsOut,
    ProfileSettingsUpdateIn,
)
from services.database import get_db
from services.gamification_service import GamificationService
from services.profile_service import ProfileService

router = APIRouter(tags=["profile"])


@router.get("/settings", response_model=ProfileSettingsOut)
async def get_profile_settings(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ProfileService.get_settings(db, user["sub"])


@router.put("/settings", response_model=ProfileSettingsOut)
async def update_profile_settings(
    payload: ProfileSettingsUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ProfileService.update_settings(
        db,
        user["sub"],
        payload.dict(exclude_unset=True),
    )


@router.get("/game", response_model=ProfileGameSummaryOut)
async def get_profile_game_summary(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await GamificationService.get_game_summary(db, user["sub"], user)
