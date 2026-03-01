import os
import time

import requests
from fastapi import HTTPException


BASE_URL = "https://api.twelvedata.com"
_CACHE = {}

RANGE_CONFIG = {
    "1D": {"interval": "5min", "outputsize": 78},
    "1W": {"interval": "1h", "outputsize": 120},
    "1M": {"interval": "1day", "outputsize": 30},
    "1Y": {"interval": "1week", "outputsize": 52},
}


def _get_api_key() -> str:
    api_key = os.getenv("TWELVEDATA_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="TWELVEDATA_API_KEY is not set")
    return api_key


def _cache_get(key):
    entry = _CACHE.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if expires_at <= time.time():
        _CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key, payload, ttl_seconds: int):
    _CACHE[key] = (time.time() + ttl_seconds, payload)


def _request(endpoint: str, params: dict):
    try:
        response = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=12)
        payload = response.json()
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Failed to reach Twelve Data")
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from Twelve Data")

    if isinstance(payload, dict) and payload.get("status") == "error":
        raise HTTPException(status_code=400, detail=payload.get("message", "Twelve Data error"))
    return payload


def fetch_chart(symbol: str, range_key: str):
    range_key = (range_key or "1M").upper()
    if range_key not in RANGE_CONFIG:
        range_key = "1M"

    symbol = symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")

    cache_key = f"chart:{symbol}:{range_key}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    cfg = RANGE_CONFIG[range_key]
    payload = _request(
        "time_series",
        {
            "symbol": symbol,
            "interval": cfg["interval"],
            "outputsize": cfg["outputsize"],
            "apikey": _get_api_key(),
        },
    )

    values = payload.get("values") or []
    points = []
    for item in reversed(values):
        close_value = item.get("close")
        dt = item.get("datetime")
        if close_value is None or not dt:
            continue
        try:
            close = float(close_value)
        except (TypeError, ValueError):
            continue
        points.append({"t": dt, "c": close})

    if not points:
        raise HTTPException(status_code=404, detail=f"No chart data for symbol {symbol}")

    meta = payload.get("meta") or {}
    result = {
        "symbol": meta.get("symbol", symbol),
        "interval": meta.get("interval", cfg["interval"]),
        "currency": meta.get("currency"),
        "exchange": meta.get("exchange"),
        "points": points,
    }
    _cache_set(cache_key, result, ttl_seconds=60)
    return result


def fetch_quote(symbol: str):
    symbol = symbol.upper().strip()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")

    cache_key = f"quote:{symbol}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    payload = _request(
        "quote",
        {
            "symbol": symbol,
            "apikey": _get_api_key(),
        },
    )

    close_raw = payload.get("close") or payload.get("price")
    previous_raw = payload.get("previous_close")
    try:
        close = float(close_raw) if close_raw is not None else None
    except (TypeError, ValueError):
        close = None
    try:
        previous_close = float(previous_raw) if previous_raw is not None else None
    except (TypeError, ValueError):
        previous_close = None

    change_percent = None
    if close is not None and previous_close not in (None, 0):
        change_percent = ((close - previous_close) / previous_close) * 100

    result = {
        "symbol": symbol,
        "name": payload.get("name"),
        "price": close,
        "previous_close": previous_close,
        "change_percent": change_percent,
    }
    _cache_set(cache_key, result, ttl_seconds=30)
    return result
