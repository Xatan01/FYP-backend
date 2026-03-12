from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.consultation_schema import (
    ConsultationBookOut,
    ConsultationBookingCreateIn,
    ConsultationBookingOut,
    ConsultationBookingsOut,
    ConsultationChatMessageCreateIn,
    ConsultationChatMessageOut,
    ConsultationChatMessagesOut,
    ConsultationExpertOut,
    ConsultationExpertsOut,
)
from services.consultation_service import ConsultationService
from services.database import get_db

router = APIRouter(tags=["consultation"])


@router.get("/experts", response_model=ConsultationExpertsOut)
async def list_consultation_experts(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_user),
):
    return await ConsultationService.list_experts(db)


@router.get("/experts/{expert_id}", response_model=ConsultationExpertOut)
async def get_consultation_expert(
    expert_id: int,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_user),
):
    return await ConsultationService.get_expert(db, expert_id)


@router.post("/bookings", response_model=ConsultationBookingOut)
async def create_consultation_booking(
    payload: ConsultationBookingCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ConsultationService.create_booking(
        db=db,
        user_id=user["sub"],
        expert_id=payload.expert_id,
        topic=payload.topic,
        preferred_time=payload.preferred_time,
        initial_message=payload.initial_message,
    )


@router.get("/bookings", response_model=ConsultationBookingsOut)
async def list_consultation_bookings(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ConsultationService.list_bookings(db, user["sub"])


@router.post("/bookings/{booking_id}/book", response_model=ConsultationBookOut)
async def mark_consultation_booking_as_booked(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ConsultationService.mark_booking_as_booked(db, user["sub"], booking_id)


@router.get("/bookings/{booking_id}/messages", response_model=ConsultationChatMessagesOut)
async def list_consultation_messages(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ConsultationService.list_messages(db, user["sub"], booking_id)


@router.post("/bookings/{booking_id}/messages", response_model=ConsultationChatMessageOut)
async def send_consultation_message(
    booking_id: int,
    payload: ConsultationChatMessageCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ConsultationService.send_message(
        db=db,
        user_id=user["sub"],
        booking_id=booking_id,
        message=payload.message,
    )
