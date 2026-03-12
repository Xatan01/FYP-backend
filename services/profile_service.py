import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.profile_model import UserAppSettings


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ProfileService:
    @staticmethod
    def _to_user_uuid(user_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid user id in token")

    @staticmethod
    def _serialize(settings: UserAppSettings):
        return {
            "user_id": settings.user_id,
            "theme_preference": settings.theme_preference,
            "volume_level": int(settings.volume_level),
            "notifications_enabled": bool(settings.notifications_enabled),
            "market_alerts_enabled": bool(settings.market_alerts_enabled),
            "social_alerts_enabled": bool(settings.social_alerts_enabled),
            "lesson_reminders_enabled": bool(settings.lesson_reminders_enabled),
            "updated_at": settings.updated_at,
        }

    @staticmethod
    async def _ensure_settings(db: AsyncSession, user_uuid: uuid.UUID):
        settings = (
            await db.execute(select(UserAppSettings).where(UserAppSettings.user_id == user_uuid))
        ).scalar_one_or_none()
        if settings:
            return settings, False

        settings = UserAppSettings(user_id=user_uuid)
        db.add(settings)
        await db.flush()
        return settings, True

    @staticmethod
    async def get_settings(db: AsyncSession, user_id: str):
        user_uuid = ProfileService._to_user_uuid(user_id)
        settings, created = await ProfileService._ensure_settings(db, user_uuid)
        if created:
            await db.commit()
            await db.refresh(settings)
        return ProfileService._serialize(settings)

    @staticmethod
    async def update_settings(db: AsyncSession, user_id: str, payload: dict):
        user_uuid = ProfileService._to_user_uuid(user_id)
        settings, _ = await ProfileService._ensure_settings(db, user_uuid)

        updates = dict(payload or {})
        theme = updates.get("theme_preference")
        if theme is not None:
            normalized_theme = str(theme).strip().lower()
            if normalized_theme not in {"light", "dark"}:
                raise HTTPException(status_code=400, detail="theme_preference must be 'light' or 'dark'")
            settings.theme_preference = normalized_theme

        if updates.get("volume_level") is not None:
            try:
                volume_level = int(updates["volume_level"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="volume_level must be an integer")
            if volume_level < 0 or volume_level > 100:
                raise HTTPException(status_code=400, detail="volume_level must be between 0 and 100")
            settings.volume_level = volume_level

        for key in (
            "notifications_enabled",
            "market_alerts_enabled",
            "social_alerts_enabled",
            "lesson_reminders_enabled",
        ):
            if key in updates and updates[key] is not None:
                setattr(settings, key, bool(updates[key]))

        settings.updated_at = _now_utc()
        await db.commit()
        await db.refresh(settings)
        return ProfileService._serialize(settings)
