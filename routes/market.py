from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from routes.auth import require_user
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
