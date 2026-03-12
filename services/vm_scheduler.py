import asyncio
import os
from datetime import datetime, timedelta, timezone

from services.database import SessionLocal
from services.virtual_market_service import VirtualMarketService


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _next_run_utc(hour: int, minute: int) -> datetime:
    now = datetime.now(timezone.utc)
    run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run_at <= now:
        run_at = run_at + timedelta(days=1)
    return run_at


async def run_daily_price_sync_forever():
    enabled = _env_bool("VM_ENABLE_SCHEDULER", True)
    if not enabled:
        print("[vm-scheduler] Disabled by VM_ENABLE_SCHEDULER")
        return

    try:
        hour = int((os.getenv("VM_SCHEDULER_UTC_HOUR") or "23").strip())
        minute = int((os.getenv("VM_SCHEDULER_UTC_MINUTE") or "30").strip())
    except ValueError:
        hour, minute = 23, 30

    hour = max(0, min(hour, 23))
    minute = max(0, min(minute, 59))

    print(f"[vm-scheduler] Started. Daily sync at {hour:02d}:{minute:02d} UTC")

    while True:
        next_run = _next_run_utc(hour, minute)
        delay = max((next_run - datetime.now(timezone.utc)).total_seconds(), 0)
        print(f"[vm-scheduler] Next run at {next_run.isoformat()}")

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            print("[vm-scheduler] Cancelled before next run")
            raise

        try:
            async with SessionLocal() as db:
                result = await VirtualMarketService.sync_daily_prices(db, symbols_filter=None)
            print(
                "[vm-scheduler] Sync complete "
                f"(synced={result['synced_count']}, failed={result['failed_count']})"
            )
        except asyncio.CancelledError:
            print("[vm-scheduler] Cancelled during sync")
            raise
        except Exception as exc:
            print(f"[vm-scheduler] Sync failed: {exc}")
