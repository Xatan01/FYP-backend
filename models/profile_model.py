from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from services.database import Base


class UserAppSettings(Base):
    __tablename__ = "user_app_settings"
    __table_args__ = (
        CheckConstraint(
            "theme_preference IN ('light','dark')",
            name="ck_user_app_settings_theme_preference",
        ),
        CheckConstraint(
            "volume_level >= 0 AND volume_level <= 100",
            name="ck_user_app_settings_volume_level_range",
        ),
    )

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    theme_preference = Column(String(10), nullable=False, server_default="dark")
    volume_level = Column(SmallInteger, nullable=False, server_default="70")
    notifications_enabled = Column(Boolean, nullable=False, server_default="true")
    market_alerts_enabled = Column(Boolean, nullable=False, server_default="true")
    social_alerts_enabled = Column(Boolean, nullable=False, server_default="true")
    lesson_reminders_enabled = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
