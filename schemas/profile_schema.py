from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProfileSettingsOut(BaseModel):
    user_id: UUID
    theme_preference: str
    volume_level: int
    notifications_enabled: bool
    market_alerts_enabled: bool
    social_alerts_enabled: bool
    lesson_reminders_enabled: bool
    updated_at: datetime


class ProfileSettingsUpdateIn(BaseModel):
    theme_preference: Optional[str] = Field(default=None)
    volume_level: Optional[int] = Field(default=None, ge=0, le=100)
    notifications_enabled: Optional[bool] = None
    market_alerts_enabled: Optional[bool] = None
    social_alerts_enabled: Optional[bool] = None
    lesson_reminders_enabled: Optional[bool] = None
