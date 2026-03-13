import asyncio
import os
from datetime import datetime, timedelta, timezone

from services.database import SessionLocal
from services.market_news_service import MarketNewsService


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _next_run_utc(hour: int, minute: int) -> datetime:
    now = datetime.now(timezone.utc)
    run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run_at <= now:
        run_at = run_at + timedelta(days=1)
    return run_at


async def run_daily_news_sync_forever():
    enabled = _env_bool("NEWS_ENABLE_SCHEDULER", True)
    if not enabled:
        print("[news-scheduler] Disabled by NEWS_ENABLE_SCHEDULER")
        return

    run_on_startup = _env_bool("NEWS_SYNC_ON_STARTUP", True)

    try:
        hour = int((os.getenv("NEWS_SCHEDULER_UTC_HOUR") or "0").strip())
        minute = int((os.getenv("NEWS_SCHEDULER_UTC_MINUTE") or "10").strip())
    except ValueError:
        hour, minute = 0, 10

    hour = max(0, min(hour, 23))
    minute = max(0, min(minute, 59))

    print(f"[news-scheduler] Started. Daily sync at {hour:02d}:{minute:02d} UTC")

    if run_on_startup:
        try:
            async with SessionLocal() as db:
                result = await MarketNewsService.sync_daily_news(db)
            print(
                "[news-scheduler] Startup sync complete "
                f"(stored={result['stored_count']}, news_date={result['news_date']})"
            )
        except asyncio.CancelledError:
            print("[news-scheduler] Cancelled during startup sync")
            raise
        except Exception as exc:
            print(f"[news-scheduler] Startup sync failed: {exc}")

    while True:
        next_run = _next_run_utc(hour, minute)
        delay = max((next_run - datetime.now(timezone.utc)).total_seconds(), 0)
        print(f"[news-scheduler] Next run at {next_run.isoformat()}")

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            print("[news-scheduler] Cancelled before next run")
            raise

        try:
            async with SessionLocal() as db:
                result = await MarketNewsService.sync_daily_news(db)
            print(
                "[news-scheduler] Sync complete "
                f"(stored={result['stored_count']}, news_date={result['news_date']})"
            )
        except asyncio.CancelledError:
            print("[news-scheduler] Cancelled during sync")
            raise
        except Exception as exc:
            print(f"[news-scheduler] Sync failed: {exc}")
