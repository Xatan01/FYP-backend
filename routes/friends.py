from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.friends_schema import (
    FriendProfileOut,
    FriendProfileUpsertIn,
    FriendRemoveOut,
    FriendSearchOut,
    FriendshipActionOut,
    FriendshipListOut,
    FriendshipRequestCreateIn,
)
from services.database import get_db
from services.friends_service import FriendsService

router = APIRouter(tags=["friends"])


@router.get("/profile/me", response_model=FriendProfileOut)
async def get_my_friend_profile(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.get_my_profile(db, user["sub"], user)


@router.put("/profile/me", response_model=FriendProfileOut)
async def upsert_my_friend_profile(
    payload: FriendProfileUpsertIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.upsert_my_profile(db, user["sub"], user, payload.username)


@router.get("/search", response_model=FriendSearchOut)
async def search_friend_profiles(
    query: str = Query(..., min_length=2, max_length=24),
    limit: int = Query(10, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.search_users(db, user["sub"], user, query, limit)


@router.post("/requests", response_model=FriendshipActionOut)
async def create_friend_request(
    payload: FriendshipRequestCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.send_request(db, user["sub"], user, payload.username)


@router.get("/requests/incoming", response_model=FriendshipListOut)
async def get_incoming_friend_requests(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.list_incoming_requests(db, user["sub"], user)


@router.get("/requests/outgoing", response_model=FriendshipListOut)
async def get_outgoing_friend_requests(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.list_outgoing_requests(db, user["sub"], user)


@router.post("/requests/{friendship_id}/accept", response_model=FriendshipActionOut)
async def accept_friend_request(
    friendship_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.respond_to_request(db, user["sub"], user, friendship_id, accept=True)


@router.post("/requests/{friendship_id}/decline", response_model=FriendshipActionOut)
async def decline_friend_request(
    friendship_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.respond_to_request(db, user["sub"], user, friendship_id, accept=False)


@router.get("", response_model=FriendshipListOut)
async def list_my_friends(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.list_friends(db, user["sub"], user)


@router.delete("/{friend_user_id}", response_model=FriendRemoveOut)
async def remove_friend(
    friend_user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await FriendsService.remove_friend(db, user["sub"], user, friend_user_id)
