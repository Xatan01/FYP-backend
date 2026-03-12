import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.consultation_model import (
    ConsultationBooking,
    ConsultationChatMessage,
    ConsultationExpert,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(value):
    if value is None:
        return None
    return float(value)


class ConsultationService:
    @staticmethod
    def _to_user_uuid(user_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid user id in token")

    @staticmethod
    def _default_experts():
        return [
            {
                "display_name": "Alicia Tan",
                "designation": "Independent Financial Advisor",
                "specialty": "ETF Portfolio Planning",
                "years_experience": 9,
                "rating": Decimal("4.80"),
                "hourly_rate": Decimal("120.00"),
                "currency": "USD",
                "bio": "Builds long-term ETF strategies and rebalancing plans for young professionals.",
                "avatar_url": None,
                "is_active": True,
            },
            {
                "display_name": "Marcus Lee",
                "designation": "Licensed Wealth Consultant",
                "specialty": "Retirement And Risk Planning",
                "years_experience": 12,
                "rating": Decimal("4.70"),
                "hourly_rate": Decimal("140.00"),
                "currency": "USD",
                "bio": "Focuses on retirement cashflow planning and portfolio downside protection.",
                "avatar_url": None,
                "is_active": True,
            },
            {
                "display_name": "Priya Nair",
                "designation": "Certified Financial Planner",
                "specialty": "Goal-Based Personal Finance",
                "years_experience": 7,
                "rating": Decimal("4.90"),
                "hourly_rate": Decimal("130.00"),
                "currency": "USD",
                "bio": "Helps clients align savings, debt, and investment plans with major life goals.",
                "avatar_url": None,
                "is_active": True,
            },
        ]

    @staticmethod
    async def _ensure_seed_experts(db: AsyncSession):
        expert_count = (await db.execute(select(func.count(ConsultationExpert.expert_id)))).scalar_one()
        if int(expert_count or 0) > 0:
            return False

        for payload in ConsultationService._default_experts():
            db.add(ConsultationExpert(**payload, updated_at=_now_utc()))
        await db.flush()
        return True

    @staticmethod
    def _serialize_expert(expert: ConsultationExpert):
        return {
            "expert_id": int(expert.expert_id),
            "display_name": expert.display_name,
            "designation": expert.designation,
            "specialty": expert.specialty,
            "years_experience": int(expert.years_experience),
            "rating": _to_float(expert.rating),
            "hourly_rate": _to_float(expert.hourly_rate),
            "currency": expert.currency,
            "bio": expert.bio,
            "avatar_url": expert.avatar_url,
            "is_active": bool(expert.is_active),
        }

    @staticmethod
    def _serialize_booking(booking: ConsultationBooking, expert: ConsultationExpert):
        return {
            "booking_id": int(booking.booking_id),
            "user_id": booking.user_id,
            "expert": ConsultationService._serialize_expert(expert),
            "topic": booking.topic,
            "preferred_time": booking.preferred_time,
            "booked": bool(booking.booked),
            "booked_at": booking.booked_at,
            "booking_source": booking.booking_source,
            "created_at": booking.created_at,
            "updated_at": booking.updated_at,
        }

    @staticmethod
    def _serialize_message(message: ConsultationChatMessage):
        return {
            "message_id": int(message.message_id),
            "booking_id": int(message.booking_id),
            "sender": message.sender,
            "message": message.message_text,
            "created_at": message.created_at,
        }

    @staticmethod
    async def _get_active_expert_by_id(db: AsyncSession, expert_id: int):
        expert = (
            await db.execute(
                select(ConsultationExpert).where(
                    ConsultationExpert.expert_id == expert_id,
                    ConsultationExpert.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not expert:
            raise HTTPException(status_code=404, detail="Expert not found")
        return expert

    @staticmethod
    async def _get_booking_for_user(db: AsyncSession, user_uuid: uuid.UUID, booking_id: int):
        row = (
            await db.execute(
                select(ConsultationBooking, ConsultationExpert)
                .join(
                    ConsultationExpert,
                    ConsultationExpert.expert_id == ConsultationBooking.expert_id,
                )
                .where(
                    ConsultationBooking.booking_id == booking_id,
                    ConsultationBooking.user_id == user_uuid,
                )
            )
        ).one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Booking not found")
        return row

    @staticmethod
    async def list_experts(db: AsyncSession):
        seeded = await ConsultationService._ensure_seed_experts(db)

        experts = (
            await db.execute(
                select(ConsultationExpert)
                .where(ConsultationExpert.is_active.is_(True))
                .order_by(
                    desc(ConsultationExpert.rating),
                    desc(ConsultationExpert.years_experience),
                    ConsultationExpert.display_name.asc(),
                )
            )
        ).scalars().all()

        if seeded:
            await db.commit()

        return {
            "items": [ConsultationService._serialize_expert(expert) for expert in experts],
            "updated_at": _now_utc(),
        }

    @staticmethod
    async def get_expert(db: AsyncSession, expert_id: int):
        expert = await ConsultationService._get_active_expert_by_id(db, expert_id)
        return ConsultationService._serialize_expert(expert)

    @staticmethod
    async def create_booking(
        db: AsyncSession,
        user_id: str,
        expert_id: int,
        topic: str | None,
        preferred_time: datetime | None,
        initial_message: str | None,
    ):
        user_uuid = ConsultationService._to_user_uuid(user_id)
        expert = await ConsultationService._get_active_expert_by_id(db, expert_id)

        clean_topic = str(topic or "").strip() or None
        clean_message = str(initial_message or "").strip()

        booking = ConsultationBooking(
            user_id=user_uuid,
            expert_id=expert.expert_id,
            topic=clean_topic,
            preferred_time=preferred_time,
            booked=False,
            booked_at=None,
            booking_source="consultation_page",
            updated_at=_now_utc(),
        )
        db.add(booking)
        await db.flush()

        if clean_message:
            db.add(
                ConsultationChatMessage(
                    booking_id=booking.booking_id,
                    sender="user",
                    message_text=clean_message,
                )
            )
            booking.updated_at = _now_utc()

        await db.commit()
        await db.refresh(booking)
        return ConsultationService._serialize_booking(booking, expert)

    @staticmethod
    async def list_bookings(db: AsyncSession, user_id: str):
        user_uuid = ConsultationService._to_user_uuid(user_id)

        rows = (
            await db.execute(
                select(ConsultationBooking, ConsultationExpert)
                .join(
                    ConsultationExpert,
                    ConsultationExpert.expert_id == ConsultationBooking.expert_id,
                )
                .where(ConsultationBooking.user_id == user_uuid)
                .order_by(
                    ConsultationBooking.updated_at.desc(),
                    ConsultationBooking.booking_id.desc(),
                )
            )
        ).all()

        return {
            "items": [
                ConsultationService._serialize_booking(booking, expert) for booking, expert in rows
            ]
        }

    @staticmethod
    async def mark_booking_as_booked(db: AsyncSession, user_id: str, booking_id: int):
        user_uuid = ConsultationService._to_user_uuid(user_id)
        booking, expert = await ConsultationService._get_booking_for_user(db, user_uuid, booking_id)

        if not booking.booked:
            booking.booked = True
            booking.booked_at = _now_utc()
            booking.updated_at = _now_utc()
            db.add(
                ConsultationChatMessage(
                    booking_id=booking.booking_id,
                    sender="system",
                    message_text="Booking confirmed. Lead marked for advisor billing.",
                )
            )
            await db.commit()
            await db.refresh(booking)

        return {
            "success": True,
            "booking": ConsultationService._serialize_booking(booking, expert),
        }

    @staticmethod
    async def list_messages(db: AsyncSession, user_id: str, booking_id: int):
        user_uuid = ConsultationService._to_user_uuid(user_id)
        await ConsultationService._get_booking_for_user(db, user_uuid, booking_id)

        messages = (
            await db.execute(
                select(ConsultationChatMessage)
                .where(ConsultationChatMessage.booking_id == booking_id)
                .order_by(
                    ConsultationChatMessage.created_at.asc(),
                    ConsultationChatMessage.message_id.asc(),
                )
            )
        ).scalars().all()

        return {
            "booking_id": int(booking_id),
            "items": [ConsultationService._serialize_message(message) for message in messages],
        }

    @staticmethod
    async def send_message(db: AsyncSession, user_id: str, booking_id: int, message: str):
        user_uuid = ConsultationService._to_user_uuid(user_id)
        booking, _ = await ConsultationService._get_booking_for_user(db, user_uuid, booking_id)

        clean_message = str(message or "").strip()
        if not clean_message:
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        chat = ConsultationChatMessage(
            booking_id=booking.booking_id,
            sender="user",
            message_text=clean_message,
        )
        db.add(chat)
        booking.updated_at = _now_utc()

        await db.commit()
        await db.refresh(chat)

        return ConsultationService._serialize_message(chat)
