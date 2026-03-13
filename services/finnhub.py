import os
from datetime import datetime, timezone

import requests
from fastapi import HTTPException


BASE_URL = "https://finnhub.io/api/v1"


def _get_api_key() -> str:
    api_key = (os.getenv("FINNHUB_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="FINNHUB_API_KEY is not set")
    return api_key


def _request(endpoint: str, params: dict):
    payload = dict(params)
    payload["token"] = _get_api_key()

    try:
        response = requests.get(f"{BASE_URL}/{endpoint}", params=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Failed to reach Finnhub")
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from Finnhub")


def _to_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _normalize_symbols(value) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    items = [symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()]
    return list(dict.fromkeys(items))


def fetch_general_news(category: str = "general") -> list[dict]:
    payload = _request("news", {"category": category})
    if not isinstance(payload, list):
        raise HTTPException(status_code=502, detail="Unexpected Finnhub news response")

    items = []
    for article in payload:
        published_at = _to_datetime(article.get("datetime"))
        headline = str(article.get("headline") or "").strip()
        url = str(article.get("url") or "").strip()
        if not headline or not url or published_at is None:
            continue

        items.append(
            {
                "provider": "finnhub",
                "category": str(article.get("category") or category or "general").strip().lower(),
                "headline": headline,
                "summary": str(article.get("summary") or "").strip() or None,
                "url": url,
                "image_url": str(article.get("image") or "").strip() or None,
                "source": str(article.get("source") or "").strip() or None,
                "symbols": _normalize_symbols(article.get("related")),
                "external_id": str(article.get("id")) if article.get("id") is not None else None,
                "published_at": published_at,
            }
        )
    return items
