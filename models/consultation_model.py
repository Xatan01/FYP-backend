from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from services.database import Base


class ConsultationExpert(Base):
    __tablename__ = "consultation_experts"
    __table_args__ = (
        CheckConstraint(
            "years_experience >= 0 AND years_experience <= 80",
            name="ck_consultation_experts_years_experience_range",
        ),
        CheckConstraint(
            "rating >= 0 AND rating <= 5",
            name="ck_consultation_experts_rating_range",
        ),
        CheckConstraint(
            "hourly_rate > 0",
            name="ck_consultation_experts_hourly_rate_positive",
        ),
    )

    expert_id = Column(BigInteger, primary_key=True, autoincrement=True)
    display_name = Column(String(120), nullable=False)
    designation = Column(String(120), nullable=False)
    specialty = Column(String(120), nullable=False)
    years_experience = Column(SmallInteger, nullable=False, server_default="1")
    rating = Column(Numeric(3, 2), nullable=False, server_default="0")
    hourly_rate = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(8), nullable=False, server_default="USD")
    bio = Column(Text, nullable=True)
    avatar_url = Column(String(512), nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConsultationBooking(Base):
    __tablename__ = "consultation_bookings"
    __table_args__ = (
        CheckConstraint(
            "(booked = false) OR (booked = true AND booked_at IS NOT NULL)",
            name="ck_consultation_bookings_booked_requires_booked_at",
        ),
    )

    booking_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    expert_id = Column(
        BigInteger,
        ForeignKey("consultation_experts.expert_id", ondelete="RESTRICT"),
        nullable=False,
    )
    topic = Column(String(255), nullable=True)
    preferred_time = Column(DateTime(timezone=True), nullable=True)
    booked = Column(Boolean, nullable=False, server_default="false")
    booked_at = Column(DateTime(timezone=True), nullable=True)
    booking_source = Column(String(32), nullable=False, server_default="consultation_page")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConsultationChatMessage(Base):
    __tablename__ = "consultation_chat_messages"
    __table_args__ = (
        CheckConstraint(
            "sender IN ('user','expert','system')",
            name="ck_consultation_chat_messages_sender",
        ),
    )

    message_id = Column(BigInteger, primary_key=True, autoincrement=True)
    booking_id = Column(
        BigInteger,
        ForeignKey("consultation_bookings.booking_id", ondelete="CASCADE"),
        nullable=False,
    )
    sender = Column(String(16), nullable=False)
    message_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
