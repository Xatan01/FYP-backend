import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.Learn.user_learn_model import QuizAttempts
from models.friends_model import SocialFriendship, SocialUserProfile
from models.virtual_market_model import VMPriceDaily, VMUserPosition, VMUserWallet


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _initial_cash() -> Decimal:
    raw = (os.getenv("VM_INITIAL_CASH") or "10000").strip()
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal("10000")


def _to_float(value) -> float:
    if value is None:
        return 0.0
    return float(value)


class LeaderboardService:
    @staticmethod
    async def _get_friend_user_ids(db: AsyncSession, me_user_id: UUID):
        rows = (
            await db.execute(
                select(SocialFriendship).where(
                    SocialFriendship.status == "accepted",
                    or_(
                        SocialFriendship.user_low_id == me_user_id,
                        SocialFriendship.user_high_id == me_user_id,
                    ),
                )
            )
        ).scalars().all()
        friend_ids = set()
        for row in rows:
            friend_ids.add(row.user_high_id if row.user_low_id == me_user_id else row.user_low_id)
        friend_ids.add(me_user_id)
        return friend_ids

    @staticmethod
    async def _load_user_stats(db: AsyncSession):
        profiles = (
            await db.execute(
                select(SocialUserProfile).order_by(SocialUserProfile.username_lower.asc())
            )
        ).scalars().all()
        if not profiles:
            return []

        user_ids = [profile.user_id for profile in profiles]

        xp_rows = (
            await db.execute(
                select(
                    QuizAttempts.user_id,
                    func.coalesce(func.sum(QuizAttempts.points_awarded), 0).label("xp"),
                )
                .where(QuizAttempts.user_id.in_(user_ids))
                .group_by(QuizAttempts.user_id)
            )
        ).all()
        xp_map = {row.user_id: int(row.xp or 0) for row in xp_rows}

        wallet_rows = (
            await db.execute(
                select(VMUserWallet.user_id, VMUserWallet.cash_balance).where(
                    VMUserWallet.user_id.in_(user_ids)
                )
            )
        ).all()
        wallet_map = {row.user_id: row.cash_balance for row in wallet_rows}

        latest_subquery = (
            select(
                VMPriceDaily.stock_id.label("stock_id"),
                func.max(VMPriceDaily.price_date).label("max_price_date"),
            )
            .group_by(VMPriceDaily.stock_id)
            .subquery()
        )
        market_rows = (
            await db.execute(
                select(
                    VMUserPosition.user_id,
                    func.coalesce(func.sum(VMUserPosition.quantity * VMPriceDaily.close), 0).label(
                        "market_value"
                    ),
                )
                .join(
                    latest_subquery,
                    latest_subquery.c.stock_id == VMUserPosition.stock_id,
                )
                .join(
                    VMPriceDaily,
                    and_(
                        VMPriceDaily.stock_id == latest_subquery.c.stock_id,
                        VMPriceDaily.price_date == latest_subquery.c.max_price_date,
                    ),
                )
                .where(
                    VMUserPosition.user_id.in_(user_ids),
                    VMUserPosition.quantity > 0,
                )
                .group_by(VMUserPosition.user_id)
            )
        ).all()
        market_map = {row.user_id: row.market_value for row in market_rows}

        initial_cash = _initial_cash()
        stats = []
        for profile in profiles:
            wallet_balance = wallet_map.get(profile.user_id)
            has_virtual_market = wallet_balance is not None
            market_value = market_map.get(profile.user_id, Decimal("0"))
            total_equity = None
            equity_return_pct = None

            if has_virtual_market:
                total_equity = Decimal(str(wallet_balance)) + Decimal(str(market_value))
                if initial_cash > 0:
                    equity_return_pct = ((total_equity - initial_cash) / initial_cash) * Decimal("100")
                else:
                    equity_return_pct = Decimal("0")

            stats.append(
                {
                    "user_id": profile.user_id,
                    "username": profile.username,
                    "xp": xp_map.get(profile.user_id, 0),
                    "equity": total_equity,
                    "equity_return_pct": equity_return_pct,
                }
            )

        return stats

    @staticmethod
    def _rank_rows(stats: list[dict], key: str, limit: int | None, only_with_value: bool):
        rows = stats
        if only_with_value:
            rows = [row for row in stats if row.get(key) is not None]

        ranked = sorted(
            rows,
            key=lambda row: (float(row[key] or 0), row["username"].lower()),
            reverse=True,
        )
        if limit is None:
            slice_rows = ranked
        else:
            slice_rows = ranked[:limit]

        output = []
        for idx, row in enumerate(slice_rows, start=1):
            output.append(
                {
                    "rank": idx,
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "value": _to_float(row[key]),
                }
            )
        return output

    @staticmethod
    async def get_leaderboards(db: AsyncSession, me_user_id: str | UUID):
        if isinstance(me_user_id, str):
            me_user_id = uuid.UUID(me_user_id)
        stats = await LeaderboardService._load_user_stats(db)
        friend_ids = await LeaderboardService._get_friend_user_ids(db, me_user_id)
        friend_stats = [row for row in stats if row["user_id"] in friend_ids]
        global_limit = 10

        global_section = {
            "xp": LeaderboardService._rank_rows(
                stats,
                "xp",
                global_limit,
                only_with_value=False,
            ),
            "equity": LeaderboardService._rank_rows(
                stats,
                "equity",
                global_limit,
                only_with_value=True,
            ),
            "equity_return_pct": LeaderboardService._rank_rows(
                stats,
                "equity_return_pct",
                global_limit,
                only_with_value=True,
            ),
        }
        friends_section = {
            "xp": LeaderboardService._rank_rows(
                friend_stats,
                "xp",
                None,
                only_with_value=False,
            ),
            "equity": LeaderboardService._rank_rows(
                friend_stats,
                "equity",
                None,
                only_with_value=True,
            ),
            "equity_return_pct": LeaderboardService._rank_rows(
                friend_stats,
                "equity_return_pct",
                None,
                only_with_value=True,
            ),
        }

        return {
            "global": global_section,
            "friends": friends_section,
            "generated_at": _now_utc(),
        }
