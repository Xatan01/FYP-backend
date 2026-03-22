from __future__ import annotations

import argparse
import types
import warnings
import pickle
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── paste your existing file name here if different ──────────────────────────
# This file imports everything from the code you already have.
# Make sure both files are in the same folder.
from train_universal import (          # ← rename this to match your filename (without .py)
    download_history,
    build_features,
    get_feature_columns,
    build_model_factories,
    split_development_holdout,
    _train_universal_ensemble,
    RegimeFilter,
    BULLISH_SIGNAL,
    BEARISH_SIGNAL,
    NEUTRAL_SIGNAL,
)

# ─────────────────────────────────────────────────────────────────────────────
# PERSONALITY CONFIGS
# Each personality controls: how aggressively to trade, max position size,
# volatility target, and how cautious to be before pulling the trigger.
# ─────────────────────────────────────────────────────────────────────────────

PERSONALITIES = {
    "conservative": {
        # Needs very high confidence before acting
        "bull_threshold":    0.65,   # needs 65% bull probability to buy
        "bear_threshold":    0.70,   # needs 70% bear probability to short
        "margin_threshold":  0.10,   # winning signal must beat others by 10%
        "max_allocation":    0.10,   # max 10% of portfolio per trade
        "target_annual_vol": 0.08,   # targets 8% annual volatility
        "max_drawdown_limit":0.12,   # halves size if drawdown exceeds 12%
        "kelly_fraction":    0.20,   # very fractional kelly
        "neutral_action":    "cash", # goes to cash when unsure
        "description": "Low risk. Waits for strong signals. Small positions. Goes to cash when uncertain.",
    },
    "balanced": {
        "bull_threshold":    0.55,
        "bear_threshold":    0.60,
        "margin_threshold":  0.05,
        "max_allocation":    0.18,
        "target_annual_vol": 0.14,
        "max_drawdown_limit":0.18,
        "kelly_fraction":    0.25,
        "neutral_action":    "hold",
        "description": "Moderate risk. Standard thresholds. Holds position when signal is mixed.",
    },
    "aggressive": {
        "bull_threshold":    0.45,   # acts on weaker signals
        "bear_threshold":    0.50,
        "margin_threshold":  0.02,   # very small margin needed
        "max_allocation":    0.30,   # up to 30% of portfolio
        "target_annual_vol": 0.22,   # targets 22% annual volatility
        "max_drawdown_limit":0.28,   # tolerates large drawdowns
        "kelly_fraction":    0.30,
        "neutral_action":    "hold",
        "description": "High risk/reward. Acts on weaker signals. Large positions. Stays invested.",
    },
}

# Tickers the model is trained on — add more for better generalisation
DEFAULT_TRAIN_TICKERS = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
BENCHMARK_TICKER      = "SPY"
TRAIN_START           = "2018-01-01"
TRAIN_END             = "2024-12-31"
MODEL_DIR             = Path("./models")


# ─────────────────────────────────────────────────────────────────────────────
# TRAIN  (run once)
# ─────────────────────────────────────────────────────────────────────────────

def train_all_personalities(
    tickers: list[str] = DEFAULT_TRAIN_TICKERS,
    start:   str       = TRAIN_START,
    end:     str       = TRAIN_END,
    model_dir: Path    = MODEL_DIR,
) -> None:
    """
    Train one ensemble model per personality and save to disk.
    Call this once. After that, use get_signal() directly.
    """
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading benchmark ({BENCHMARK_TICKER})…")
    benchmark = download_history(BENCHMARK_TICKER, start, end)

    print(f"Downloading {len(tickers)} tickers…")
    price_data: dict[str, pd.DataFrame] = {}
    for t in tickers:
        print(f"  {t}", end=" ", flush=True)
        try:
            price_data[t] = download_history(t, start, end)
            print("OK")
        except Exception as e:
            print(f"SKIP ({e})")

    if not price_data:
        raise RuntimeError("No ticker data downloaded successfully.")

    model_factories = build_model_factories(rf_estimators=200, calibration_splits=3, horizon=5)

    for personality_name, cfg in PERSONALITIES.items():
        print(f"\n{'='*60}")
        print(f"Training: {personality_name.upper()}")
        print(f"  {cfg['description']}")
        print(f"{'='*60}")

        # Build features for each ticker with this personality's thresholds
        dev_by_ticker: dict[str, pd.DataFrame] = {}
        for ticker, price_df in price_data.items():
            try:
                featured = build_features(
                    price_df,
                    benchmark_data=benchmark,
                    horizon=5,
                    bull_threshold=0.02,   # label thresholds (fixed; personality affects trading not labelling)
                    bear_threshold=-0.02,
                )
                dev, _ = split_development_holdout(featured, holdout_size=0.15, horizon=5)
                if len(dev) > 100:
                    dev_by_ticker[ticker] = dev
            except Exception as e:
                print(f"  [warn] feature build failed for {ticker}: {e}")

        if not dev_by_ticker:
            print(f"  [error] No data available, skipping {personality_name}")
            continue

        feature_cols = get_feature_columns(next(iter(dev_by_ticker.values())))

        ensemble = _train_universal_ensemble(
            model_factories=model_factories,
            development_by_ticker=dev_by_ticker,
            feature_cols=feature_cols,
            n_splits=5,
            horizon=5,
        )

        # Save ensemble + regime filter together in one bundle
        spy_ret = benchmark["Close"].pct_change().dropna()
        regime  = RegimeFilter().fit(spy_ret)

        bundle = {
            "ensemble":     ensemble,
            "regime":       regime,
            "feature_cols": feature_cols,
            "personality":  personality_name,
            "cfg":          cfg,
            "benchmark_last_date": benchmark.index[-1],
        }

        out_path = model_dir / f"{personality_name}.pkl"
        with open(out_path, "wb") as f:
            pickle.dump(bundle, f)
        print(f"  Saved → {out_path}")

    print("\nAll personalities trained. You can now call get_signal().")


# ─────────────────────────────────────────────────────────────────────────────
# LOAD CACHED BUNDLES  (fast — loaded once per session)
# ─────────────────────────────────────────────────────────────────────────────

_BUNDLE_CACHE: dict[str, dict] = {}

def _load_bundle(personality: str, model_dir: Path = MODEL_DIR) -> dict:
    if personality not in _BUNDLE_CACHE:
        path = model_dir / f"{personality}.pkl"
        if not path.exists():
            raise FileNotFoundError(
                f"No trained model found for '{personality}' at {path}.\n"
                f"Run:  python trading_system.py --train"
            )
        with open(path, "rb") as f:
            _BUNDLE_CACHE[personality] = pickle.load(f)
        print(f"[loaded] {personality} model from {path}")
    return _BUNDLE_CACHE[personality]


# ─────────────────────────────────────────────────────────────────────────────
# GET SIGNAL  (your main app API)
# ─────────────────────────────────────────────────────────────────────────────

def get_signal(
    ticker: str,
    personality: Literal["conservative", "balanced", "aggressive"] = "balanced",
    lookback_days: int = 300,
    model_dir: Path = MODEL_DIR,
) -> dict:
    """
    Returns a trading signal for `ticker` using the given personality.

    Parameters
    ----------
    ticker        : stock symbol e.g. "AAPL"
    personality   : "conservative" | "balanced" | "aggressive"
    lookback_days : how many calendar days of history to fetch (min ~250)
    model_dir     : where the trained .pkl files live

    Returns
    -------
    dict with keys:
        signal      → "BUY" | "SELL" | "HOLD"
        bull_prob   → float 0-1, model's confidence in a rise
        bear_prob   → float 0-1, model's confidence in a fall
        hold_prob   → float 0-1
        size        → suggested position size as fraction of portfolio (0-1)
        regime      → 1 = bull market, 0 = bear market (SPY-based)
        personality → which personality was used
        date        → the date of the last data point used
    """
    bundle       = _load_bundle(personality, model_dir)
    ensemble     = bundle["ensemble"]
    regime_model = bundle["regime"]
    feature_cols = bundle["feature_cols"]
    cfg          = bundle["cfg"]

    # Fetch recent price data for this ticker + benchmark
    from datetime import datetime, timedelta
    end   = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    price_df  = download_history(ticker, start, end)
    benchmark = download_history(BENCHMARK_TICKER, start, end)

    featured = build_features(
        price_df,
        benchmark_data=benchmark,
        horizon=5,
        bull_threshold=0.02,
        bear_threshold=-0.02,
    )

    # Keep only the features the model was trained on
    feat_present = [c for c in feature_cols if c in featured.columns]
    missing      = set(feature_cols) - set(feat_present)
    if missing:
        # Fill any missing features with 0 rather than crashing
        for col in missing:
            featured[col] = 0.0

    X = featured[feature_cols].iloc[[-1]]   # just the most recent row

    # Get model probabilities
    proba_df  = ensemble.predict_proba_df(X)
    proba_row = proba_df.iloc[0]

    bull_prob = float(proba_row.get(BULLISH_SIGNAL, 0.0))
    bear_prob = float(proba_row.get(BEARISH_SIGNAL, 0.0))
    hold_prob = float(proba_row.get(NEUTRAL_SIGNAL, 0.0))

    # Determine signal using personality thresholds
    bull_margin = bull_prob - max(bear_prob, hold_prob)
    bear_margin = bear_prob - max(bull_prob, hold_prob)

    if bull_prob >= cfg["bull_threshold"] and bull_margin >= cfg["margin_threshold"]:
        signal = BULLISH_SIGNAL
    elif bear_prob >= cfg["bear_threshold"] and bear_margin >= cfg["margin_threshold"]:
        signal = BEARISH_SIGNAL
    else:
        signal = NEUTRAL_SIGNAL

    # Regime detection (1 = bull, 0 = bear)
    spy_ret = benchmark["Close"].pct_change().dropna()
    regimes = regime_model.predict(spy_ret)
    current_regime = int(regimes.iloc[-1]) if len(regimes) > 0 else 1

    # Position size suggestion
    # Start from max_allocation, scale down in bear regime
    base_size   = cfg["max_allocation"]
    regime_scale = 0.6 if current_regime == 0 else 1.0
    # Scale by confidence: how far above threshold is the signal?
    if signal == BULLISH_SIGNAL:
        confidence_scale = min((bull_prob - cfg["bull_threshold"]) / (1 - cfg["bull_threshold"]) + 0.5, 1.0)
    elif signal == BEARISH_SIGNAL:
        confidence_scale = min((bear_prob - cfg["bear_threshold"]) / (1 - cfg["bear_threshold"]) + 0.5, 1.0)
    else:
        confidence_scale = 0.0

    suggested_size = round(base_size * regime_scale * confidence_scale, 4)

    return {
        "signal":      signal,
        "bull_prob":   round(bull_prob, 4),
        "bear_prob":   round(bear_prob, 4),
        "hold_prob":   round(hold_prob, 4),
        "size":        suggested_size,
        "regime":      current_regime,   # 1=bull, 0=bear
        "personality": personality,
        "date":        str(featured.index[-1].date()),
        "ticker":      ticker.upper(),
    }


def get_all_signals(ticker: str, model_dir: Path = MODEL_DIR) -> dict:
    """
    Get signals from all 3 personalities at once.

    Returns
    -------
    dict keyed by personality name, each value is a get_signal() result.

    Example:
        signals = get_all_signals("TSLA")
        signals["aggressive"]["signal"]   # "BUY"
        signals["conservative"]["signal"] # "HOLD"
    """
    return {p: get_signal(ticker, personality=p, model_dir=model_dir) for p in PERSONALITIES}


def get_signal_bundle_meta(personality: str, model_dir: Path = MODEL_DIR) -> dict:
    bundle = _load_bundle(personality, model_dir)
    path = model_dir / f"{personality}.pkl"
    benchmark_last_date = bundle.get("benchmark_last_date")
    if hasattr(benchmark_last_date, "date"):
        benchmark_last_date = benchmark_last_date.date()

    bundle_updated_at = None
    if path.exists():
        bundle_updated_at = datetime.fromtimestamp(path.stat().st_mtime)

    return {
        "personality": personality,
        "bundle_updated_at": bundle_updated_at,
        "benchmark_last_date": benchmark_last_date,
        "cfg": bundle.get("cfg", {}),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train",  action="store_true", help="Train all personality models")
    parser.add_argument("--signal", type=str,            help="Get signal for a ticker, e.g. --signal AAPL")
    parser.add_argument("--personality", default="all",  help="conservative | balanced | aggressive | all")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TRAIN_TICKERS),
                        help="Comma-separated tickers for training")
    args = parser.parse_args()

    if args.train:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        train_all_personalities(tickers=tickers)

    elif args.signal:
        ticker = args.signal.upper()
        if args.personality == "all":
            results = get_all_signals(ticker)
            print(f"\nSignals for {ticker}:")
            print(f"{'Personality':<15} {'Signal':<6} {'Bull%':>6} {'Bear%':>6} {'Size':>6} {'Regime':>8}")
            print("-" * 55)
            for p, r in results.items():
                regime_str = "BULL" if r["regime"] == 1 else "BEAR"
                print(f"{p:<15} {r['signal']:<6} {r['bull_prob']:>6.1%} {r['bear_prob']:>6.1%} "
                      f"{r['size']:>6.1%} {regime_str:>8}")
        else:
            r = get_signal(ticker, personality=args.personality)
            print(r)

    else:
        parser.print_help()
        print("\nExamples:")
        print("  python trading_system.py --train")
        print("  python trading_system.py --signal AAPL")
        print("  python trading_system.py --signal TSLA --personality aggressive")
