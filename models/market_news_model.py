from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import func

from services.database import Base


class MarketNews(Base):
    __tablename__ = "market_news"
    __table_args__ = (
        CheckConstraint("rank >= 1", name="market_news_rank_check"),
        UniqueConstraint("news_date", "rank", name="market_news_news_date_rank_key"),
        UniqueConstraint("news_date", "url", name="market_news_news_date_url_key"),
    )

    news_id = Column(BigInteger, primary_key=True, autoincrement=True)
    news_date = Column(Date, nullable=False)
    rank = Column(Integer, nullable=False)
    provider = Column(String, nullable=False, server_default="finnhub")
    category = Column(String, nullable=False, server_default="general")
    headline = Column(Text, nullable=False)
    summary = Column(Text)
    url = Column(Text, nullable=False)
    image_url = Column(Text)
    source = Column(Text)
    symbols = Column(ARRAY(String), nullable=False, server_default="{}")
    external_id = Column(String)
    published_at = Column(DateTime(timezone=True), nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
