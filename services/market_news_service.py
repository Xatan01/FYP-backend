import os
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.market_news_model import MarketNews
from services.finnhub import fetch_general_news


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MarketNewsService:
    IMPORTANT_KEYWORDS = (
        "fed",
        "federal reserve",
        "interest rate",
        "rates",
        "inflation",
        "cpi",
        "ppi",
        "jobs",
        "gdp",
        "tariff",
        "earnings",
        "guidance",
        "forecast",
        "recession",
        "downgrade",
        "upgrade",
        "acquisition",
        "merger",
        "ipo",
        "sec",
        "tesla",
        "nvidia",
        "apple",
        "microsoft",
        "amazon",
        "google",
        "meta",
        "s&p 500",
        "nasdaq",
    )

    @staticmethod
    def _items_per_day() -> int:
        raw = (os.getenv("NEWS_ITEMS_PER_DAY") or "5").strip()
        try:
            count = int(raw)
        except ValueError:
            count = 5
        return max(1, min(count, 20))

    @staticmethod
    def validate_sync_admin_key(provided_key: str | None):
        expected_key = (os.getenv("NEWS_SYNC_ADMIN_KEY") or "").strip()
        if not expected_key:
            raise HTTPException(status_code=500, detail="NEWS_SYNC_ADMIN_KEY is not set")
        if not provided_key or provided_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")

    @staticmethod
    def _score_article(article: dict) -> tuple[int, float]:
        headline = str(article.get("headline") or "").lower()
        summary = str(article.get("summary") or "").lower()
        combined = f"{headline} {summary}"

        keyword_hits = sum(1 for keyword in MarketNewsService.IMPORTANT_KEYWORDS if keyword in combined)
        symbols_bonus = min(len(article.get("symbols") or []), 3)
        source_bonus = 1 if article.get("source") else 0
        summary_bonus = 1 if article.get("summary") else 0
        image_bonus = 1 if article.get("image_url") else 0
        published_at = article.get("published_at")
        recency_score = published_at.timestamp() if published_at else 0.0
        return (keyword_hits * 5) + (symbols_bonus * 2) + source_bonus + summary_bonus + image_bonus, recency_score

    @staticmethod
    def _dedupe_and_rank(candidates: list[dict], limit: int) -> list[dict]:
        deduped = []
        seen_urls = set()
        seen_headlines = set()
        source_counts: dict[str, int] = {}

        sorted_candidates = sorted(
            candidates,
            key=MarketNewsService._score_article,
            reverse=True,
        )

        for article in sorted_candidates:
            url = str(article.get("url") or "").strip()
            headline = str(article.get("headline") or "").strip().lower()
            source = str(article.get("source") or "").strip().lower()
            if not url or not headline:
                continue
            if url in seen_urls or headline in seen_headlines:
                continue
            if source and source_counts.get(source, 0) >= 2:
                continue

            seen_urls.add(url)
            seen_headlines.add(headline)
            if source:
                source_counts[source] = source_counts.get(source, 0) + 1
            deduped.append(article)

            if len(deduped) >= limit:
                break

        return deduped

    @staticmethod
    async def get_latest_news(db: AsyncSession, limit: int | None = None):
        target_limit = limit or MarketNewsService._items_per_day()
        latest_news_date = (
            await db.execute(select(MarketNews.news_date).order_by(MarketNews.news_date.desc()).limit(1))
        ).scalar_one_or_none()

        if latest_news_date is None:
            return {
                "news_date": None,
                "stale": True,
                "items": [],
                "updated_at": _now_utc(),
            }

        rows = (
            await db.execute(
                select(MarketNews)
                .where(MarketNews.news_date == latest_news_date)
                .order_by(MarketNews.rank.asc())
                .limit(target_limit)
            )
        ).scalars().all()

        today_utc = _now_utc().date()
        return {
            "news_date": latest_news_date,
            "stale": latest_news_date < today_utc,
            "items": [
                {
                    "news_id": int(row.news_id),
                    "rank": row.rank,
                    "provider": row.provider,
                    "category": row.category,
                    "headline": row.headline,
                    "summary": row.summary,
                    "url": row.url,
                    "image_url": row.image_url,
                    "source": row.source,
                    "symbols": list(row.symbols or []),
                    "external_id": row.external_id,
                    "published_at": row.published_at,
                    "fetched_at": row.fetched_at,
                }
                for row in rows
            ],
            "updated_at": _now_utc(),
        }

    @staticmethod
    async def sync_daily_news(
        db: AsyncSession,
        *,
        news_date: date | None = None,
        category: str = "general",
    ):
        target_date = news_date or _now_utc().date()
        limit = MarketNewsService._items_per_day()
        candidates = fetch_general_news(category=category)
        if not candidates:
            raise HTTPException(status_code=502, detail="Finnhub returned no news items")

        ranked_items = MarketNewsService._dedupe_and_rank(candidates, limit)
        if not ranked_items:
            raise HTTPException(status_code=502, detail="No valid news items available after filtering")

        try:
            await db.execute(delete(MarketNews).where(MarketNews.news_date == target_date))
            stored_rows = []
            fetched_at = _now_utc()

            for index, article in enumerate(ranked_items, start=1):
                row = MarketNews(
                    news_date=target_date,
                    rank=index,
                    provider=article["provider"],
                    category=article["category"],
                    headline=article["headline"],
                    summary=article["summary"],
                    url=article["url"],
                    image_url=article["image_url"],
                    source=article["source"],
                    symbols=article["symbols"],
                    external_id=article["external_id"],
                    published_at=article["published_at"],
                    fetched_at=fetched_at,
                )
                db.add(row)
                stored_rows.append(row)

            await db.commit()

            return {
                "news_date": target_date,
                "stored_count": len(stored_rows),
                "items": [
                    {
                        "rank": row.rank,
                        "headline": row.headline,
                        "source": row.source,
                        "published_at": row.published_at,
                        "url": row.url,
                        "symbols": list(row.symbols or []),
                    }
                    for row in stored_rows
                ],
                "updated_at": _now_utc(),
            }
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise
