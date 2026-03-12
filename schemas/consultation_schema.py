from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ConsultationExpertOut(BaseModel):
    expert_id: int
    display_name: str
    designation: str
    specialty: str
    years_experience: int
    rating: float
    hourly_rate: float
    currency: str
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool


class ConsultationExpertsOut(BaseModel):
    items: list[ConsultationExpertOut]
    updated_at: datetime


class ConsultationBookingCreateIn(BaseModel):
    expert_id: int = Field(gt=0)
    topic: Optional[str] = Field(default=None, max_length=255)
    preferred_time: Optional[datetime] = None
    initial_message: Optional[str] = Field(default=None, max_length=4000)


class ConsultationBookingOut(BaseModel):
    booking_id: int
    user_id: UUID
    expert: ConsultationExpertOut
    topic: Optional[str] = None
    preferred_time: Optional[datetime] = None
    booked: bool
    booked_at: Optional[datetime] = None
    booking_source: str
    created_at: datetime
    updated_at: datetime


class ConsultationBookingsOut(BaseModel):
    items: list[ConsultationBookingOut]


class ConsultationBookOut(BaseModel):
    success: bool
    booking: ConsultationBookingOut


class ConsultationChatMessageCreateIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ConsultationChatMessageOut(BaseModel):
    message_id: int
    booking_id: int
    sender: str
    message: str
    created_at: datetime


class ConsultationChatMessagesOut(BaseModel):
    booking_id: int
    items: list[ConsultationChatMessageOut]
