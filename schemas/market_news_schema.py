from datetime import date, datetime

from pydantic import BaseModel


class MarketNewsItemOut(BaseModel):
    news_id: int
    rank: int
    provider: str
    category: str
    headline: str
    summary: str | None = None
    url: str
    image_url: str | None = None
    source: str | None = None
    symbols: list[str]
    external_id: str | None = None
    published_at: datetime
    fetched_at: datetime


class MarketNewsOut(BaseModel):
    news_date: date | None = None
    stale: bool
    items: list[MarketNewsItemOut]
    updated_at: datetime


class MarketNewsSyncItemOut(BaseModel):
    rank: int
    headline: str
    source: str | None = None
    published_at: datetime
    url: str
    symbols: list[str]


class MarketNewsSyncOut(BaseModel):
    news_date: date
    stored_count: int
    items: list[MarketNewsSyncItemOut]
    updated_at: datetime
