from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from routes.auth import require_user
from services.twelvedata import fetch_chart, fetch_quote

router = APIRouter(dependencies=[Depends(require_user)], tags=["market"])


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
