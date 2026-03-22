from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from routes.auth import require_user
from schemas.ai_trader_schema import PersonalitySignalOut, TraderSignalsOut
from services.trading_system import (
    BENCHMARK_TICKER,
    MODEL_DIR,
    PERSONALITIES,
    get_signal,
    get_signal_bundle_meta,
)

router = APIRouter(tags=["ai-trader"])


@router.get("/signals", response_model=TraderSignalsOut)
async def get_ai_trader_signals(
    symbol: str = Query(..., min_length=1, max_length=16),
    lookback_days: int = Query(300, ge=250, le=1000),
    user=Depends(require_user),
):
    ticker = str(symbol or "").strip().upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="Ticker symbol is required.")

    items: list[PersonalitySignalOut] = []
    latest_bundle_updated_at = None
    latest_benchmark_last_date = None

    try:
        for personality_name, cfg in PERSONALITIES.items():
            signal = get_signal(ticker, personality=personality_name, lookback_days=lookback_days)
            meta = get_signal_bundle_meta(personality_name, MODEL_DIR)

            bundle_updated_at = meta.get("bundle_updated_at")
            if bundle_updated_at and (
                latest_bundle_updated_at is None or bundle_updated_at > latest_bundle_updated_at
            ):
                latest_bundle_updated_at = bundle_updated_at

            benchmark_last_date = meta.get("benchmark_last_date")
            if benchmark_last_date and (
                latest_benchmark_last_date is None or benchmark_last_date > latest_benchmark_last_date
            ):
                latest_benchmark_last_date = benchmark_last_date

            items.append(
                PersonalitySignalOut(
                    personality=personality_name,
                    description=cfg["description"],
                    signal=signal["signal"],
                    bull_prob=signal["bull_prob"],
                    bear_prob=signal["bear_prob"],
                    hold_prob=signal["hold_prob"],
                    size=signal["size"],
                    regime=signal["regime"],
                    regime_label="bull" if signal["regime"] == 1 else "bear",
                    as_of_date=signal["date"],
                    ticker=signal["ticker"],
                    bull_threshold=cfg["bull_threshold"],
                    bear_threshold=cfg["bear_threshold"],
                    margin_threshold=cfg["margin_threshold"],
                    max_allocation=cfg["max_allocation"],
                    target_annual_vol=cfg["target_annual_vol"],
                    max_drawdown_limit=cfg["max_drawdown_limit"],
                    kelly_fraction=cfg["kelly_fraction"],
                    neutral_action=cfg["neutral_action"],
                )
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to generate AI trader signals for {ticker}: {exc}",
        ) from exc

    return TraderSignalsOut(
        ticker=ticker,
        benchmark_ticker=BENCHMARK_TICKER,
        lookback_days=lookback_days,
        generated_at=datetime.now(timezone.utc),
        model_bundle_updated_at=latest_bundle_updated_at,
        benchmark_last_date=latest_benchmark_last_date,
        items=items,
    )
