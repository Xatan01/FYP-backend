from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class FriendProfileOut(BaseModel):
    user_id: UUID
    username: str


class FriendProfileUpsertIn(BaseModel):
    username: str = Field(min_length=3, max_length=24)


class FriendshipRequestCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=24)


class FriendshipOut(BaseModel):
    friendship_id: UUID
    user_id: UUID
    username: str
    status: str
    requested_by: UUID
    created_at: datetime
    updated_at: datetime
    responded_at: Optional[datetime] = None


class FriendshipListOut(BaseModel):
    items: list[FriendshipOut]


class FriendSearchResultOut(BaseModel):
    user_id: UUID
    username: str
    relation: str
    friendship_id: Optional[UUID] = None


class FriendSearchOut(BaseModel):
    items: list[FriendSearchResultOut]


class FriendshipActionOut(BaseModel):
    success: bool
    friendship_id: UUID
    status: str


class FriendRemoveOut(BaseModel):
    success: bool
    removed_user_id: UUID
