import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from services.database import Base


class SocialUserProfile(Base):
    __tablename__ = "social_user_profiles"

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    username = Column(String(24), nullable=False, unique=True)
    username_lower = Column(String(24), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SocialFriendship(Base):
    __tablename__ = "social_friendships"
    __table_args__ = (
        UniqueConstraint("user_low_id", "user_high_id", name="uq_social_friendship_pair"),
        CheckConstraint("user_low_id <> user_high_id", name="ck_social_friendship_distinct_users"),
        CheckConstraint(
            "requested_by = user_low_id OR requested_by = user_high_id",
            name="ck_social_friendship_requested_by_member",
        ),
        CheckConstraint(
            "status IN ('pending','accepted','declined')",
            name="ck_social_friendship_status",
        ),
    )

    friendship_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_low_id = Column(
        UUID(as_uuid=True),
        ForeignKey("social_user_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_high_id = Column(
        UUID(as_uuid=True),
        ForeignKey("social_user_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by = Column(
        UUID(as_uuid=True),
        ForeignKey("social_user_profiles.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(16), nullable=False, server_default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    responded_at = Column(DateTime(timezone=True))
