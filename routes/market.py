from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.market_news_schema import MarketNewsOut, MarketNewsSyncOut
from services.database import get_db
from services.market_news_service import MarketNewsService
from services.twelvedata import fetch_chart, fetch_quote, fetch_quotes, search_symbols

router = APIRouter(dependencies=[Depends(require_user)], tags=["market"])

DEFAULT_POPULAR_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "TSLA", "NVDA"]


@router.get("/chart")
def get_chart(symbol: str = Query(...), range: str = Query("1M")):
    normalized_range = (range or "1M").upper()
    chart = fetch_chart(symbol, normalized_range)
    quote = fetch_quote(symbol)
    return {
        "symbol": chart["symbol"],
        "range": normalized_range,
        "interval": chart["interval"],
        "currency": chart["currency"],
        "exchange": chart["exchange"],
        "price": quote["price"],
        "change_percent": quote["change_percent"],
        "points": chart["points"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/search")
def market_search(query: str = Query(...), limit: int = Query(8, ge=1, le=20)):
    return {"results": search_symbols(query, limit)}


@router.get("/popular")
def market_popular():
    quotes = fetch_quotes(DEFAULT_POPULAR_SYMBOLS)
    return {
        "symbols": DEFAULT_POPULAR_SYMBOLS,
        "items": quotes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/quotes")
def market_quotes(symbols: str = Query(...)):
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        return {"items": []}
    quotes = fetch_quotes(symbol_list)
    return {
        "items": quotes,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/news", response_model=MarketNewsOut)
async def market_news(
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
):
    return await MarketNewsService.get_latest_news(db, limit=limit)


@router.post("/admin/sync-news", response_model=MarketNewsSyncOut)
async def sync_market_news(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    db: AsyncSession = Depends(get_db),
):
    MarketNewsService.validate_sync_admin_key(x_admin_key)
    return await MarketNewsService.sync_daily_news(db)
