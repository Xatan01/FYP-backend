import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.friends_model import SocialFriendship, SocialUserProfile

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{3,24}$")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_user_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid user id in token")


def _normalize_username(username: str) -> str:
    clean = str(username or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail="Username is required")
    if not USERNAME_PATTERN.fullmatch(clean):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-24 chars and use only letters, numbers, ., _, -",
        )
    return clean


def _friend_pair(user_a: uuid.UUID, user_b: uuid.UUID):
    return (user_a, user_b) if str(user_a) < str(user_b) else (user_b, user_a)


def _serialize_profile(profile: SocialUserProfile):
    return {
        "user_id": profile.user_id,
        "username": profile.username,
    }


def _serialize_friendship(friendship: SocialFriendship, other_user_id: uuid.UUID, other_username: str):
    return {
        "friendship_id": friendship.friendship_id,
        "user_id": other_user_id,
        "username": other_username,
        "status": friendship.status,
        "requested_by": friendship.requested_by,
        "created_at": friendship.created_at,
        "updated_at": friendship.updated_at,
        "responded_at": friendship.responded_at,
    }


class FriendsService:
    @staticmethod
    def _username_from_claims(user_claims: dict) -> str | None:
        user_metadata = user_claims.get("user_metadata")
        if isinstance(user_metadata, dict):
            candidate = user_metadata.get("username")
            if candidate and isinstance(candidate, str):
                return candidate.strip()
        email = user_claims.get("email")
        if isinstance(email, str) and "@" in email:
            local = email.split("@", 1)[0].strip()
            if local:
                return local[:24]
        return None

    @staticmethod
    async def _ensure_profile(db: AsyncSession, user_id: str, user_claims: dict):
        user_uuid = _to_user_uuid(user_id)
        profile = (
            await db.execute(select(SocialUserProfile).where(SocialUserProfile.user_id == user_uuid))
        ).scalar_one_or_none()
        if profile:
            return profile

        base_username = FriendsService._username_from_claims(user_claims) or f"user{str(user_uuid)[:8]}"
        base_username = _normalize_username(re.sub(r"[^a-zA-Z0-9_.-]", "", base_username)[:24] or "user")

        candidate = base_username
        index = 1
        while True:
            existing = (
                await db.execute(
                    select(SocialUserProfile).where(
                        SocialUserProfile.username_lower == candidate.lower()
                    )
                )
            ).scalar_one_or_none()
            if not existing:
                break
            suffix = str(index)
            truncated = base_username[: max(3, 24 - len(suffix))]
            candidate = f"{truncated}{suffix}"
            index += 1

        profile = SocialUserProfile(
            user_id=user_uuid,
            username=candidate,
            username_lower=candidate.lower(),
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile

    @staticmethod
    async def get_my_profile(db: AsyncSession, user_id: str, user_claims: dict):
        profile = await FriendsService._ensure_profile(db, user_id, user_claims)
        return _serialize_profile(profile)

    @staticmethod
    async def upsert_my_profile(db: AsyncSession, user_id: str, user_claims: dict, username: str):
        user_uuid = _to_user_uuid(user_id)
        await FriendsService._ensure_profile(db, user_id, user_claims)

        clean_username = _normalize_username(username)
        existing = (
            await db.execute(
                select(SocialUserProfile).where(
                    SocialUserProfile.username_lower == clean_username.lower(),
                    SocialUserProfile.user_id != user_uuid,
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Username is already taken")

        profile = (
            await db.execute(select(SocialUserProfile).where(SocialUserProfile.user_id == user_uuid))
        ).scalar_one()
        profile.username = clean_username
        profile.username_lower = clean_username.lower()
        profile.updated_at = _now_utc()
        await db.commit()
        await db.refresh(profile)
        return _serialize_profile(profile)

    @staticmethod
    async def _friendship_map_for_user(db: AsyncSession, user_uuid: uuid.UUID):
        friendships = (
            await db.execute(
                select(SocialFriendship).where(
                    or_(
                        SocialFriendship.user_low_id == user_uuid,
                        SocialFriendship.user_high_id == user_uuid,
                    )
                )
            )
        ).scalars().all()
        by_other: dict[uuid.UUID, SocialFriendship] = {}
        for item in friendships:
            other_user_id = item.user_high_id if item.user_low_id == user_uuid else item.user_low_id
            by_other[other_user_id] = item
        return by_other

    @staticmethod
    async def search_users(
        db: AsyncSession,
        user_id: str,
        user_claims: dict,
        query: str,
        limit: int = 10,
    ):
        user_uuid = _to_user_uuid(user_id)
        await FriendsService._ensure_profile(db, user_id, user_claims)

        clean_query = str(query or "").strip().lower()
        if len(clean_query) < 2:
            return {"items": []}

        rows = (
            await db.execute(
                select(SocialUserProfile)
                .where(
                    SocialUserProfile.user_id != user_uuid,
                    SocialUserProfile.username_lower.like(f"{clean_query}%"),
                )
                .order_by(SocialUserProfile.username_lower.asc())
                .limit(limit)
            )
        ).scalars().all()

        friendship_map = await FriendsService._friendship_map_for_user(db, user_uuid)
        items = []
        for profile in rows:
            relation = "none"
            friendship_id = None
            friendship = friendship_map.get(profile.user_id)
            if friendship:
                friendship_id = friendship.friendship_id
                if friendship.status == "accepted":
                    relation = "friend"
                elif friendship.status == "pending":
                    relation = (
                        "outgoing_pending"
                        if friendship.requested_by == user_uuid
                        else "incoming_pending"
                    )
                elif friendship.status == "declined":
                    relation = "none"

            items.append(
                {
                    "user_id": profile.user_id,
                    "username": profile.username,
                    "relation": relation,
                    "friendship_id": friendship_id,
                }
            )

        return {"items": items}

    @staticmethod
    async def send_request(db: AsyncSession, user_id: str, user_claims: dict, target_username: str):
        user_uuid = _to_user_uuid(user_id)
        await FriendsService._ensure_profile(db, user_id, user_claims)

        clean_target = _normalize_username(target_username)
        target_profile = (
            await db.execute(
                select(SocialUserProfile).where(
                    SocialUserProfile.username_lower == clean_target.lower()
                )
            )
        ).scalar_one_or_none()
        if not target_profile:
            raise HTTPException(status_code=404, detail="User not found")
        if target_profile.user_id == user_uuid:
            raise HTTPException(status_code=400, detail="Cannot add yourself")

        low_id, high_id = _friend_pair(user_uuid, target_profile.user_id)
        friendship = (
            await db.execute(
                select(SocialFriendship).where(
                    SocialFriendship.user_low_id == low_id,
                    SocialFriendship.user_high_id == high_id,
                )
            )
        ).scalar_one_or_none()

        if not friendship:
            friendship = SocialFriendship(
                user_low_id=low_id,
                user_high_id=high_id,
                requested_by=user_uuid,
                status="pending",
            )
            db.add(friendship)
            await db.commit()
            await db.refresh(friendship)
            return {
                "success": True,
                "friendship_id": friendship.friendship_id,
                "status": friendship.status,
            }

        if friendship.status == "accepted":
            raise HTTPException(status_code=409, detail="Already friends")
        if friendship.status == "pending":
            if friendship.requested_by == user_uuid:
                raise HTTPException(status_code=409, detail="Friend request already sent")
            friendship.status = "accepted"
            friendship.responded_at = _now_utc()
            friendship.updated_at = _now_utc()
            await db.commit()
            return {
                "success": True,
                "friendship_id": friendship.friendship_id,
                "status": friendship.status,
            }

        # If previously declined, restart as pending.
        friendship.status = "pending"
        friendship.requested_by = user_uuid
        friendship.responded_at = None
        friendship.updated_at = _now_utc()
        await db.commit()
        return {
            "success": True,
            "friendship_id": friendship.friendship_id,
            "status": friendship.status,
        }

    @staticmethod
    async def _load_friend_profiles(db: AsyncSession, user_ids: list[uuid.UUID]):
        if not user_ids:
            return {}
        profiles = (
            await db.execute(select(SocialUserProfile).where(SocialUserProfile.user_id.in_(user_ids)))
        ).scalars().all()
        return {profile.user_id: profile for profile in profiles}

    @staticmethod
    async def list_incoming_requests(db: AsyncSession, user_id: str, user_claims: dict):
        user_uuid = _to_user_uuid(user_id)
        await FriendsService._ensure_profile(db, user_id, user_claims)

        rows = (
            await db.execute(
                select(SocialFriendship).where(
                    SocialFriendship.status == "pending",
                    or_(
                        SocialFriendship.user_low_id == user_uuid,
                        SocialFriendship.user_high_id == user_uuid,
                    ),
                    SocialFriendship.requested_by != user_uuid,
                )
            )
        ).scalars().all()
        other_ids = [
            row.user_high_id if row.user_low_id == user_uuid else row.user_low_id
            for row in rows
        ]
        profile_map = await FriendsService._load_friend_profiles(db, other_ids)

        return {
            "items": [
                _serialize_friendship(
                    row,
                    row.user_high_id if row.user_low_id == user_uuid else row.user_low_id,
                    profile_map[
                        row.user_high_id if row.user_low_id == user_uuid else row.user_low_id
                    ].username,
                )
                for row in rows
            ]
        }

    @staticmethod
    async def list_outgoing_requests(db: AsyncSession, user_id: str, user_claims: dict):
        user_uuid = _to_user_uuid(user_id)
        await FriendsService._ensure_profile(db, user_id, user_claims)

        rows = (
            await db.execute(
                select(SocialFriendship).where(
                    SocialFriendship.status == "pending",
                    or_(
                        SocialFriendship.user_low_id == user_uuid,
                        SocialFriendship.user_high_id == user_uuid,
                    ),
                    SocialFriendship.requested_by == user_uuid,
                )
            )
        ).scalars().all()
        other_ids = [
            row.user_high_id if row.user_low_id == user_uuid else row.user_low_id
            for row in rows
        ]
        profile_map = await FriendsService._load_friend_profiles(db, other_ids)

        return {
            "items": [
                _serialize_friendship(
                    row,
                    row.user_high_id if row.user_low_id == user_uuid else row.user_low_id,
                    profile_map[
                        row.user_high_id if row.user_low_id == user_uuid else row.user_low_id
                    ].username,
                )
                for row in rows
            ]
        }

    @staticmethod
    async def list_friends(db: AsyncSession, user_id: str, user_claims: dict):
        user_uuid = _to_user_uuid(user_id)
        await FriendsService._ensure_profile(db, user_id, user_claims)

        rows = (
            await db.execute(
                select(SocialFriendship).where(
                    SocialFriendship.status == "accepted",
                    or_(
                        SocialFriendship.user_low_id == user_uuid,
                        SocialFriendship.user_high_id == user_uuid,
                    ),
                )
            )
        ).scalars().all()
        other_ids = [
            row.user_high_id if row.user_low_id == user_uuid else row.user_low_id
            for row in rows
        ]
        profile_map = await FriendsService._load_friend_profiles(db, other_ids)

        return {
            "items": [
                _serialize_friendship(
                    row,
                    row.user_high_id if row.user_low_id == user_uuid else row.user_low_id,
                    profile_map[
                        row.user_high_id if row.user_low_id == user_uuid else row.user_low_id
                    ].username,
                )
                for row in rows
            ]
        }

    @staticmethod
    async def respond_to_request(
        db: AsyncSession,
        user_id: str,
        user_claims: dict,
        friendship_id: uuid.UUID,
        accept: bool,
    ):
        user_uuid = _to_user_uuid(user_id)
        await FriendsService._ensure_profile(db, user_id, user_claims)

        friendship = (
            await db.execute(
                select(SocialFriendship).where(
                    SocialFriendship.friendship_id == friendship_id,
                    SocialFriendship.status == "pending",
                    or_(
                        SocialFriendship.user_low_id == user_uuid,
                        SocialFriendship.user_high_id == user_uuid,
                    ),
                    SocialFriendship.requested_by != user_uuid,
                )
            )
        ).scalar_one_or_none()
        if not friendship:
            raise HTTPException(status_code=404, detail="Pending request not found")

        friendship.status = "accepted" if accept else "declined"
        friendship.responded_at = _now_utc()
        friendship.updated_at = _now_utc()
        await db.commit()
        return {
            "success": True,
            "friendship_id": friendship.friendship_id,
            "status": friendship.status,
        }

    @staticmethod
    async def remove_friend(db: AsyncSession, user_id: str, user_claims: dict, friend_user_id: uuid.UUID):
        user_uuid = _to_user_uuid(user_id)
        await FriendsService._ensure_profile(db, user_id, user_claims)

        if friend_user_id == user_uuid:
            raise HTTPException(status_code=400, detail="Cannot remove yourself")

        low_id, high_id = _friend_pair(user_uuid, friend_user_id)
        friendship = (
            await db.execute(
                select(SocialFriendship).where(
                    SocialFriendship.user_low_id == low_id,
                    SocialFriendship.user_high_id == high_id,
                    SocialFriendship.status == "accepted",
                )
            )
        ).scalar_one_or_none()
        if not friendship:
            raise HTTPException(status_code=404, detail="Friend not found")

        await db.delete(friendship)
        await db.commit()
        return {
            "success": True,
            "removed_user_id": friend_user_id,
        }
