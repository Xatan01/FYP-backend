from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
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


class UserExpStats(Base):
    __tablename__ = "user_exp_stats"
    __table_args__ = (
        CheckConstraint("total_xp >= 0", name="ck_user_exp_stats_total_xp_non_negative"),
        CheckConstraint("current_streak >= 0", name="ck_user_exp_stats_current_streak_non_negative"),
        CheckConstraint("longest_streak >= 0", name="ck_user_exp_stats_longest_streak_non_negative"),
        CheckConstraint(
            "current_league IN ('Bronze', 'Silver', 'Gold', 'Platinum', 'Diamond', 'Master')",
            name="ck_user_exp_stats_current_league",
        ),
    )

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    total_xp = Column(Integer, nullable=False, server_default="0")
    current_league = Column(String(32), nullable=False, server_default="Bronze")
    current_streak = Column(Integer, nullable=False, server_default="0")
    longest_streak = Column(Integer, nullable=False, server_default="0")
    last_activity_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class XPEvent(Base):
    __tablename__ = "xp_events"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('quiz_attempt', 'lesson_complete', 'daily_streak', 'manual_adjustment', 'journal_entry')",
            name="ck_xp_events_source_type",
        ),
        UniqueConstraint("user_id", "source_type", "source_id", name="uq_xp_events_user_source"),
    )

    xp_event_id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id = Column(UUID(as_uuid=True), nullable=False)
    source_type = Column(Text, nullable=False)
    source_id = Column(Text)
    xp_delta = Column(Integer, nullable=False)
    event_group = Column(Text)
    metadata_json = Column(JSON, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
