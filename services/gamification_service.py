from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.Learn.user_learn_model import QuizAttempts
from models.friends_model import SocialUserProfile
from services.friends_service import FriendsService

LEAGUE_CONFIG = [
    {"key": "bronze", "name": "Bronze", "min_xp": 0},
    {"key": "silver", "name": "Silver", "min_xp": 250},
    {"key": "gold", "name": "Gold", "min_xp": 750},
    {"key": "platinum", "name": "Platinum", "min_xp": 1500},
    {"key": "diamond", "name": "Diamond", "min_xp": 3000},
    {"key": "master", "name": "Master", "min_xp": 5000},
]

XP_RULES = {
    "basic": {"multiplier": 1.0},
    "core": {"multiplier": 1.25},
    "mastery": {"multiplier": 1.5},
}
RETRY_XP_MULTIPLIERS = {
    1: 1.0,
    2: 0.5,
    3: 0.25,
}
XP_PER_CORRECT = 10
XP_COMPLETION_BONUS = 10
XP_PASS_BONUS = 15


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


class GamificationService:
    RETRY_XP_MULTIPLIERS = RETRY_XP_MULTIPLIERS

    @staticmethod
    def retry_xp_multiplier(attempt_number: int) -> float:
        return GamificationService.RETRY_XP_MULTIPLIERS.get(int(attempt_number or 1), 0.25)

    @staticmethod
    def calculate_quiz_xp(
        total_correct: int,
        difficulty: str,
        passed: bool,
        attempt_number: int = 1,
    ) -> int:
        rules = XP_RULES.get(str(difficulty or "").strip().lower(), XP_RULES["basic"])
        base_points = XP_COMPLETION_BONUS + (max(0, int(total_correct or 0)) * XP_PER_CORRECT)
        if passed:
            base_points += XP_PASS_BONUS
        retry_multiplier = GamificationService.retry_xp_multiplier(attempt_number)
        total_multiplier = rules["multiplier"] * retry_multiplier
        return max(0, int(round(base_points * total_multiplier)))

    @staticmethod
    def league_for_xp(total_xp: int) -> dict:
        xp = max(0, int(total_xp or 0))
        current = LEAGUE_CONFIG[0]
        next_league = None

        for index, league in enumerate(LEAGUE_CONFIG):
            if xp >= league["min_xp"]:
                current = league
                next_league = LEAGUE_CONFIG[index + 1] if index + 1 < len(LEAGUE_CONFIG) else None
            else:
                break

        if not next_league:
            progress_percent = 100
            xp_to_next = 0
        else:
            span = max(1, next_league["min_xp"] - current["min_xp"])
            progress_percent = min(
                100,
                int(round(((xp - current["min_xp"]) / span) * 100)),
            )
            xp_to_next = max(0, next_league["min_xp"] - xp)

        return {
            "league_key": current["key"],
            "league": current["name"],
            "league_min_xp": current["min_xp"],
            "next_league": next_league["name"] if next_league else None,
            "next_league_key": next_league["key"] if next_league else None,
            "next_league_min_xp": next_league["min_xp"] if next_league else None,
            "xp_to_next_league": xp_to_next,
            "league_progress_percent": progress_percent,
        }

    @staticmethod
    def calculate_streak(activity_dates: Iterable[date | datetime]) -> int:
        normalized = sorted(
            {
                item
                for item in (_normalize_date(value) for value in activity_dates)
                if item is not None
            },
            reverse=True,
        )
        if not normalized:
            return 0

        today = _now_utc().date()
        cursor = normalized[0]
        if cursor not in {today, today - timedelta(days=1)}:
            return 0

        streak = 1
        for current in normalized[1:]:
            expected_previous_day = cursor - timedelta(days=1)
            if current == cursor:
                continue
            if current != expected_previous_day:
                break
            streak += 1
            cursor = current

        return streak

    @staticmethod
    async def get_total_xp(db: AsyncSession, user_id: str | UUID) -> int:
        total = (
            await db.execute(
                select(func.coalesce(func.sum(QuizAttempts.points_awarded), 0)).where(
                    QuizAttempts.user_id == user_id
                )
            )
        ).scalar_one()
        return int(total or 0)

    @staticmethod
    async def get_activity_dates(db: AsyncSession, user_id: str | UUID) -> list[date]:
        rows = (
            await db.execute(
                select(distinct(func.date(QuizAttempts.created_at))).where(
                    QuizAttempts.user_id == user_id
                )
            )
        ).scalars().all()
        return [row for row in rows if row is not None]

    @staticmethod
    async def get_last_activity_at(db: AsyncSession, user_id: str | UUID):
        return (
            await db.execute(
                select(func.max(QuizAttempts.created_at)).where(QuizAttempts.user_id == user_id)
            )
        ).scalar_one()

    @staticmethod
    async def get_game_summary(db: AsyncSession, user_id: str, user_claims: dict):
        profile = await FriendsService._ensure_profile(db, user_id, user_claims)
        total_xp = await GamificationService.get_total_xp(db, profile.user_id)
        activity_dates = await GamificationService.get_activity_dates(db, profile.user_id)
        streak = GamificationService.calculate_streak(activity_dates)
        league_data = GamificationService.league_for_xp(total_xp)
        last_activity_at = await GamificationService.get_last_activity_at(db, profile.user_id)

        return {
            "user_id": profile.user_id,
            "username": profile.username,
            "xp": total_xp,
            "streak": streak,
            "last_activity_at": last_activity_at,
            **league_data,
        }

    @staticmethod
    async def get_username_map(db: AsyncSession, user_ids: list[UUID]) -> dict[UUID, str]:
        if not user_ids:
            return {}
        rows = (
            await db.execute(
                select(SocialUserProfile.user_id, SocialUserProfile.username).where(
                    SocialUserProfile.user_id.in_(user_ids)
                )
            )
        ).all()
        return {row.user_id: row.username for row in rows}
