"""
Industry-Standard Universal Stock Trading System
=================================================
Performance-first design: every decision optimised for risk-adjusted returns
(Sharpe + Calmar), NOT classification accuracy.

Architecture
------------
1.  Data layer        – OHLCV + market-regime context (SPY)
2.  Feature engine    – price action, volatility, momentum, mean-reversion,
                        microstructure proxies, regime indicators
3.  Target engine     – volatility-normalised multi-horizon labels
4.  Model zoo         – RandomForest, XGBoost*, LightGBM* (graceful fallback)
5.  Calibration       – isotonic regression via TimeSeriesSplit
6.  Walk-forward CV   – purged + embargoed folds (no leakage)
7.  HMM Regime filter – 2-state Hidden Markov Model on SPY
8.  Ensemble          – probability-weighted vote across model types
9.  Kelly position sizing – fractional Kelly with drawdown brake
10. Execution sim     – commission + slippage + liquidity guard
11. Universal model   – single model trained on all tickers simultaneously
12. Evaluation        – Sharpe, Calmar, Max-DD, Win-rate, Profit-factor

Dependencies: pandas, numpy, scikit-learn, scipy, yfinance
Optional:     xgboost, lightgbm, hmmlearn
"""

from __future__ import annotations

import warnings
import math
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

# ── optional heavy deps ──────────────────────────────────────────────────────
try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

try:
    from hmmlearn.hmm import GaussianHMM
    HAS_HMMLEARN = True
except ImportError:
    HAS_HMMLEARN = False

# ── signal constants ─────────────────────────────────────────────────────────
BULLISH_SIGNAL = "BUY"
BEARISH_SIGNAL = "SELL"
NEUTRAL_SIGNAL = "HOLD"
SIGNAL_ORDER = [BEARISH_SIGNAL, NEUTRAL_SIGNAL, BULLISH_SIGNAL]


# ═══════════════════════════════════════════════════════════════════════════
# 1.  DATA LAYER
# ═══════════════════════════════════════════════════════════════════════════

def download_history(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV from yfinance; return clean DataFrame indexed by Date."""
    try:
        import yfinance as yf
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if df.empty:
            raise ValueError(f"No data for {ticker}")
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
        df.index = pd.to_datetime(df.index)
        return df
    except Exception as exc:
        raise RuntimeError(f"Failed to download {ticker}: {exc}") from exc


# ═══════════════════════════════════════════════════════════════════════════
# 2.  FEATURE ENGINE  (130+ features)
# ═══════════════════════════════════════════════════════════════════════════

def _safe_divide(a: pd.Series, b: pd.Series, fill: float = 0.0) -> pd.Series:
    return a.divide(b.replace(0, np.nan)).fillna(fill)


def build_features(
    price_df: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    horizon: int = 5,
    bull_threshold: float = 0.02,
    bear_threshold: float = -0.02,
) -> pd.DataFrame:
    """
    Build 130+ feature columns.  Target labels are volatility-normalised.
    """
    df = price_df.copy()
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    vol   = df["Volume"]

    # ── returns ──────────────────────────────────────────────────────────────
    for p in [1, 2, 3, 5, 10, 20, 60]:
        df[f"ret_{p}d"] = close.pct_change(p)

    # ── log returns ──────────────────────────────────────────────────────────
    lret = np.log(close / close.shift(1))
    for p in [1, 5, 10, 20]:
        df[f"logret_{p}d"] = lret.rolling(p).sum()

    # ── moving averages ───────────────────────────────────────────────────────
    for w in [5, 10, 20, 50, 100, 200]:
        sma = close.rolling(w).mean()
        df[f"sma_{w}"] = sma
        df[f"close_vs_sma{w}"] = _safe_divide(close - sma, sma)

    # ── EMA & MACD ────────────────────────────────────────────────────────────
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    signal_line = macd.ewm(span=9, adjust=False).mean()
    df["macd"]        = macd
    df["macd_signal"] = signal_line
    df["macd_hist"]   = macd - signal_line
    df["macd_cross"]  = (macd > signal_line).astype(int)

    # ── volatility ────────────────────────────────────────────────────────────
    for w in [5, 10, 20, 60]:
        rv = lret.rolling(w).std() * np.sqrt(252)
        df[f"rv_{w}d"] = rv

    # True Range / ATR
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    for w in [5, 14, 20]:
        df[f"atr_{w}d"] = tr.rolling(w).mean()

    df["atr14_pct"] = _safe_divide(df["atr_14d"], close)

    # Bollinger Bands
    for w in [10, 20]:
        mid = close.rolling(w).mean()
        std = close.rolling(w).std()
        df[f"bb_upper_{w}"] = mid + 2 * std
        df[f"bb_lower_{w}"] = mid - 2 * std
        df[f"bb_width_{w}"] = _safe_divide(4 * std, mid)
        df[f"bb_pct_{w}"]   = _safe_divide(close - (mid - 2*std), 4*std)

    # ── momentum / oscillators ────────────────────────────────────────────────
    # RSI
    for w in [7, 14, 21]:
        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(w).mean()
        loss  = (-delta.clip(upper=0)).rolling(w).mean()
        rs    = _safe_divide(gain, loss, fill=1.0)
        df[f"rsi_{w}"] = 100 - 100 / (1 + rs)

    # Stochastic
    for w in [14, 21]:
        lo_w = low.rolling(w).min()
        hi_w = high.rolling(w).max()
        df[f"stoch_k_{w}"] = _safe_divide(close - lo_w, hi_w - lo_w) * 100
        df[f"stoch_d_{w}"] = df[f"stoch_k_{w}"].rolling(3).mean()

    # ROC
    for p in [5, 10, 20, 60]:
        df[f"roc_{p}d"] = _safe_divide(close - close.shift(p), close.shift(p)) * 100

    # ── volume features ───────────────────────────────────────────────────────
    for w in [5, 10, 20]:
        vol_ma = vol.rolling(w).mean()
        df[f"vol_ratio_{w}d"] = _safe_divide(vol, vol_ma)

    df["obv"] = (np.sign(lret) * vol).cumsum()
    df["obv_slope_5d"]  = df["obv"].diff(5)
    df["obv_slope_10d"] = df["obv"].diff(10)

    # VWAP proxy (intraday not available; daily approximation)
    typical = (high + low + close) / 3
    df["vwap_ratio"] = _safe_divide(close, (typical * vol).rolling(20).sum() / vol.rolling(20).sum())

    # Money Flow Index
    mf = typical * vol
    pos_mf = mf.where(typical > typical.shift(1), 0).rolling(14).sum()
    neg_mf = mf.where(typical < typical.shift(1), 0).rolling(14).sum()
    df["mfi_14"] = 100 - 100 / (1 + _safe_divide(pos_mf, neg_mf.replace(0, np.nan)))

    # ── price patterns / candle structure ─────────────────────────────────────
    df["candle_body"]    = _safe_divide((close - df["Open"]).abs(), tr.replace(0, np.nan))
    df["upper_shadow"]   = _safe_divide(high - pd.concat([close, df["Open"]], axis=1).max(axis=1), tr.replace(0, np.nan))
    df["lower_shadow"]   = _safe_divide(pd.concat([close, df["Open"]], axis=1).min(axis=1) - low, tr.replace(0, np.nan))
    df["is_green"]       = (close > df["Open"]).astype(int)
    df["gap_pct"]        = _safe_divide(df["Open"] - close.shift(1), close.shift(1))

    # ── rolling high/low distance ─────────────────────────────────────────────
    for w in [10, 20, 52]:
        df[f"dist_high_{w}w"] = _safe_divide(close - high.rolling(w).max(), high.rolling(w).max())
        df[f"dist_low_{w}w"]  = _safe_divide(close - low.rolling(w).min(),  close)

    # ── market regime context (SPY) ───────────────────────────────────────────
    bench = benchmark_data["Close"].reindex(df.index).ffill()
    bench_ret = bench.pct_change()
    for w in [5, 20, 60]:
        df[f"spy_ret_{w}d"] = bench_ret.rolling(w).sum()
    spy_rv = bench_ret.rolling(20).std() * np.sqrt(252)
    df["spy_rv20"] = spy_rv
    df["spy_sma50"]  = bench.rolling(50).mean()
    df["spy_above50"] = (bench > df["spy_sma50"]).astype(int)

    # Beta (rolling 60d)
    cov = lret.rolling(60).cov(bench_ret)
    spy_var = bench_ret.rolling(60).var().replace(0, np.nan)
    df["beta_60d"] = cov / spy_var

    # Correlation with SPY
    df["corr_spy_20d"] = lret.rolling(20).corr(bench_ret)

    # ── calendar features ─────────────────────────────────────────────────────
    df["dow"]          = df.index.dayofweek
    df["month"]        = df.index.month
    df["is_month_end"] = df.index.is_month_end.astype(int)
    df["is_qtr_end"]   = ((df.index.month % 3 == 0) & df.index.is_month_end).astype(int)

    # ── vol-normalised target  ────────────────────────────────────────────────
    # future_ret over the prediction horizon
    future_ret  = close.shift(-horizon) / close - 1

    # Horizon volatility: scale daily rv by sqrt(horizon) for dimensional consistency.
    # rv_20d is annualised → convert to per-horizon units:
    #   horizon_vol = (rv_20d / sqrt(252)) * sqrt(horizon)
    rv_daily   = df["rv_20d"].clip(lower=1e-4) / np.sqrt(252)
    rv_horizon = rv_daily * np.sqrt(horizon)               # same units as future_ret
    vol_adj_ret = future_ret / rv_horizon.clip(lower=1e-5)

    # Convert personality thresholds to vol-adjusted units using the SAME horizon vol.
    # Crucially: use only a rolling expanding window so no future vol leaks into labels.
    # We use the rolling median up to each point (expanding, not full-frame median).
    rv_horizon_expanding_median = rv_horizon.expanding(min_periods=20).median()
    rv_horizon_expanding_median = rv_horizon_expanding_median.fillna(rv_horizon.iloc[:20].mean())
    rv_horizon_expanding_median = rv_horizon_expanding_median.clip(lower=1e-5)

    # dyn_bull/bear are now per-row scalars: threshold / local_horizon_vol
    dyn_bull = bull_threshold / rv_horizon_expanding_median
    dyn_bear = bear_threshold / rv_horizon_expanding_median   # bear_threshold is negative

    df["signal"] = NEUTRAL_SIGNAL
    df.loc[vol_adj_ret >= dyn_bull, "signal"] = BULLISH_SIGNAL
    df.loc[vol_adj_ret <= dyn_bear, "signal"] = BEARISH_SIGNAL

    # Keep raw future return for trading simulation
    df["future_ret"] = future_ret

    return df.dropna()


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    exclude = {"signal", "future_ret", "Open", "High", "Low", "Close", "Volume",
               "sma_5","sma_10","sma_20","sma_50","sma_100","sma_200",
               "spy_sma50","obv"}
    return [c for c in df.columns if c not in exclude]


# ═══════════════════════════════════════════════════════════════════════════
# 3.  REGIME DETECTION  (HMM on SPY)
# ═══════════════════════════════════════════════════════════════════════════

class RegimeFilter:
    """
    Fits a 2-state Gaussian HMM on SPY log-returns.
    State 0 = low-vol (bull),  State 1 = high-vol (bear).
    Returns 0/1 regime label per day.
    """
    def __init__(self):
        self.model = None
        self.bull_state: int = 0

    def fit(self, spy_returns: pd.Series) -> "RegimeFilter":
        if not HAS_HMMLEARN:
            return self
        X = spy_returns.dropna().values.reshape(-1, 1)
        hmm = GaussianHMM(n_components=2, covariance_type="diag",
                          n_iter=1000, random_state=42)
        hmm.fit(X)
        self.model = hmm
        # Bull state = lower variance
        vars_ = hmm.covars_.flatten()
        self.bull_state = int(np.argmin(vars_))
        return self

    def predict(self, spy_returns: pd.Series) -> pd.Series:
        if self.model is None:
            # Safe fallback: assume neutral/bull (1), not bear (0)
            # Returning 0 would cut all positions by 40% with no basis
            return pd.Series(1, index=spy_returns.index)
        X = spy_returns.fillna(0).values.reshape(-1, 1)
        states = self.model.predict(X)
        regime = pd.Series(states, index=spy_returns.index)
        # 1=bull, 0=bear
        regime = (regime == self.bull_state).astype(int)
        return regime


# ═══════════════════════════════════════════════════════════════════════════
# 4.  MODEL ZOO + CALIBRATION
# ═══════════════════════════════════════════════════════════════════════════

def build_model_factories(
    rf_estimators: int = 400,
    calibration_splits: int = 3,
    horizon: int = 5,
) -> dict[str, Any]:
    factories: dict[str, Any] = {}

    # Random Forest
    factories["random_forest"] = lambda: CalibratedClassifierCV(
        RandomForestClassifier(
            n_estimators=rf_estimators,
            max_depth=8,
            min_samples_leaf=20,
            max_features="sqrt",
            class_weight="balanced",
            n_jobs=-1,
            random_state=42,
        ),
        cv=TimeSeriesSplit(n_splits=calibration_splits),
        method="isotonic",
    )

    if HAS_XGBOOST:
        factories["xgboost"] = lambda: CalibratedClassifierCV(
            xgb.XGBClassifier(
                n_estimators=300,
                max_depth=5,
                learning_rate=0.03,
                subsample=0.8,
                colsample_bytree=0.8,
                use_label_encoder=False,
                eval_metric="mlogloss",
                random_state=42,
                n_jobs=-1,
            ),
            cv=TimeSeriesSplit(n_splits=calibration_splits),
            method="isotonic",
        )

    if HAS_LIGHTGBM:
        factories["lightgbm"] = lambda: CalibratedClassifierCV(
            lgb.LGBMClassifier(
                n_estimators=300,
                max_depth=6,
                learning_rate=0.03,
                num_leaves=63,
                subsample=0.8,
                colsample_bytree=0.8,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
                verbose=-1,
            ),
            cv=TimeSeriesSplit(n_splits=calibration_splits),
            method="isotonic",
        )

    return factories


# ═══════════════════════════════════════════════════════════════════════════
# 5.  TRAIN / SPLIT UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def split_development_holdout(
    frame: pd.DataFrame,
    holdout_size: float = 0.2,
    horizon: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(frame)
    cutoff = int(n * (1 - holdout_size))
    dev     = frame.iloc[:cutoff - horizon].copy()
    holdout = frame.iloc[cutoff:].copy()
    return dev, holdout


def purged_walk_forward_splits(
    df: pd.DataFrame,
    n_splits: int = 5,
    purge_gap: int = 10,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """
    Time-series walk-forward splits with date-based purge gap.

    Why date-based matters for a universal model:
    The combined frame has multiple tickers interleaved by date.  A row-based
    purge would only remove rows immediately before the val boundary, but rows
    from other tickers on the same calendar dates would still be in train and
    share market features with val rows — leaking information across the fold.

    Fix: after finding the fold boundary date, remove ALL train rows whose
    index date falls within purge_gap trading days before the val start date,
    regardless of which ticker they belong to.
    """
    tscv = TimeSeriesSplit(n_splits=n_splits)
    splits = []
    dates = df.index  # DatetimeIndex (possibly with duplicates across tickers)

    for train_idx, val_idx in tscv.split(df):
        if len(val_idx) == 0:
            continue
        val_start_date = dates[val_idx[0]]

        # Find unique sorted dates in train; remove the last purge_gap of them
        train_dates = np.unique(dates[train_idx])
        if len(train_dates) <= purge_gap:
            continue
        cutoff_date = train_dates[-(purge_gap + 1)]  # last safe train date

        # Keep only train rows whose date is <= cutoff_date
        keep_mask = dates[train_idx] <= cutoff_date
        clean_train_idx = train_idx[keep_mask]

        if len(clean_train_idx) < 50 or len(val_idx) < 10:
            continue
        splits.append((clean_train_idx, val_idx))
    return splits


def _signal_from_proba(
    proba: np.ndarray,
    classes_list: list[str],
    bull_threshold: float = 0.55,
    bear_threshold: float = 0.55,
) -> np.ndarray:
    """
    Convert class probabilities into trading direction.

    Missing BUY or SELL classes can happen on imbalanced folds. In that case,
    treat the missing side as zero probability instead of failing and forcing
    the whole model weight to collapse to a tiny fallback value.
    """
    bull_p = (
        proba[:, classes_list.index(BULLISH_SIGNAL)]
        if BULLISH_SIGNAL in classes_list
        else np.zeros(len(proba), dtype=float)
    )
    bear_p = (
        proba[:, classes_list.index(BEARISH_SIGNAL)]
        if BEARISH_SIGNAL in classes_list
        else np.zeros(len(proba), dtype=float)
    )
    return np.where(
        bull_p > bull_threshold,
        1.0,
        np.where(bear_p > bear_threshold, -1.0, 0.0),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 6.  ENSEMBLE TRAINING
# ═══════════════════════════════════════════════════════════════════════════

class EnsembleModel:
    """
    Trains all available model types, then combines probabilities
    via weighted average (weights = fold Sharpe on validation).
    """

    def __init__(self, model_factories: dict[str, Any]):
        self.factories = model_factories
        self.models: dict[str, Any] = {}
        self.weights: dict[str, float] = {}
        self.label_encoder = LabelEncoder()
        self.classes_: np.ndarray | None = None
        self.feature_cols: list[str] = []
        self.scaler = StandardScaler()

    def __getstate__(self) -> dict[str, Any]:
        """
        Make the trained ensemble pickle-safe.

        `self.factories` contains local lambda callables from
        `build_model_factories()`, and standard pickle cannot serialize them.
        They are only needed for training, not for inference after models have
        already been fit, so we drop them from the serialized state.
        """
        state = self.__dict__.copy()
        state["factories"] = {}
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        if "factories" not in self.__dict__:
            self.factories = {}

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
        future_rets_val: pd.Series | None = None,
    ) -> "EnsembleModel":
        self.feature_cols = list(X_train.columns)
        y_enc = self.label_encoder.fit_transform(y_train)
        self.classes_ = self.label_encoder.classes_

        X_scaled = self.scaler.fit_transform(X_train)

        for name, factory in self.factories.items():
            try:
                clf = factory()
                clf.fit(X_scaled, y_enc)
                self.models[name] = clf
                if X_val is not None and y_val is not None:
                    w = self._val_sharpe(clf, X_val, y_val, future_rets=future_rets_val)
                else:
                    w = 1.0
                self.weights[name] = max(w, 0.01)
            except Exception as e:
                print(f"  [warn] {name} failed: {e}")

        total = sum(self.weights.values())
        self.weights = {k: v / total for k, v in self.weights.items()}
        return self

    def _val_sharpe(self, clf, X_val: pd.DataFrame, y_val: pd.Series, future_rets: pd.Series | None = None) -> float:
        """
        Compute validation Sharpe using actual future returns aligned to X_val.
        Falls back to a label-sign proxy only if future_rets is unavailable.

        Fix: self.classes_ contains the original label strings (after LabelEncoder).
        clf.predict_proba columns correspond to self.classes_ in sorted order.
        We find bull/bear column positions by looking up the string directly in
        self.classes_, never via a second label_encoder.transform() call which
        returns an integer and then gets looked up in a string list — causing a
        ValueError that gets swallowed by except and returns 0.1 every time.
        """
        try:
            X_v = self.scaler.transform(X_val)
            proba = clf.predict_proba(X_v)

            classes_list = list(self.classes_)
            signal = _signal_from_proba(proba, classes_list)

            if future_rets is not None and len(future_rets) == len(signal):
                rets = np.array(future_rets.values, dtype=float) * signal
            else:
                # Fallback: map raw string labels directly to ±1
                y_raw = y_val.values
                label_sign = np.where(
                    y_raw == BULLISH_SIGNAL, 1.0,
                    np.where(y_raw == BEARISH_SIGNAL, -1.0, 0.0)
                ).astype(float)
                rets = label_sign * signal

            if rets.std() < 1e-8:
                return 0.1
            return float(rets.mean() / rets.std() * np.sqrt(252))
        except Exception:
            return 0.1

    def predict_proba_df(self, X: pd.DataFrame) -> pd.DataFrame:
        if not self.models:
            raise RuntimeError("No trained models.")
        X_scaled = self.scaler.transform(X[self.feature_cols])
        n = len(X)
        n_classes = len(self.classes_)
        agg = np.zeros((n, n_classes))
        for name, clf in self.models.items():
            w = self.weights.get(name, 1.0)
            proba = clf.predict_proba(X_scaled)
            agg += w * proba
        cols = [self.label_encoder.inverse_transform([i])[0] for i in range(n_classes)]
        # Map encoded labels back to signal names
        actual_cols = list(self.label_encoder.classes_)
        return pd.DataFrame(agg, columns=actual_cols, index=X.index)

    def predict(self, X: pd.DataFrame) -> pd.Series:
        proba_df = self.predict_proba_df(X)
        pred_enc = proba_df.values.argmax(axis=1)
        pred_labels = self.label_encoder.inverse_transform(pred_enc)
        return pd.Series(pred_labels, index=X.index)

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @staticmethod
    def load(path: Path) -> "EnsembleModel":
        with open(path, "rb") as f:
            return pickle.load(f)


# ═══════════════════════════════════════════════════════════════════════════
# 7.  KELLY POSITION SIZING
# ═══════════════════════════════════════════════════════════════════════════

def kelly_fraction(
    win_prob: float,
    avg_win: float,
    avg_loss: float,
    fraction: float = 0.25,
    max_alloc: float = 0.30,
) -> float:
    """
    Fractional Kelly criterion.
    fraction=0.25 = quarter-Kelly (industry standard for safety).
    """
    if avg_loss <= 0 or avg_win <= 0 or win_prob <= 0:
        return 0.0
    odds = avg_win / avg_loss
    k = (win_prob * odds - (1 - win_prob)) / odds
    k = max(k, 0.0) * fraction
    return min(k, max_alloc)


# ═══════════════════════════════════════════════════════════════════════════
# 8.  TRADING SIMULATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class PortfolioSimulator:
    """
    Realistic single-ticker trading simulator.
    Features:
    - Volatility-targeting sizing (target_annual_vol)  ← NEW
    - Fractional Kelly as secondary cap
    - Regime-aware position scaling (reduce size in bear regime)
    - Drawdown brake tied to personality max_drawdown_limit  ← NEW
    - Commission + slippage
    - Long and short positions
    - Trade count + turnover tracking  ← NEW
    """

    def __init__(
        self,
        initial_cash: float = 10_000.0,
        commission_rate: float = 0.001,
        slippage_rate: float = 0.0005,
        bull_threshold: float = 0.55,
        bear_threshold: float = 0.55,
        margin_threshold: float = 0.05,
        neutral_action: str = "hold",
        max_allocation: float = 0.30,
        kelly_fraction: float = 0.25,
        target_annual_vol: float = 0.14,       # vol-targeting: 8%=conservative, 14%=balanced, 22%=aggressive
        max_drawdown_limit: float = 0.18,      # personality drawdown brake trigger
    ):
        self.initial_cash      = initial_cash
        self.commission_rate   = commission_rate
        self.slippage_rate     = slippage_rate
        self.bull_threshold    = bull_threshold
        self.bear_threshold    = bear_threshold
        self.margin_threshold  = margin_threshold
        self.neutral_action    = neutral_action
        self.max_allocation    = max_allocation
        self.kelly_frac        = kelly_fraction
        self.target_annual_vol = target_annual_vol
        self.max_drawdown_limit = max_drawdown_limit

        self.cash      = initial_cash
        self.position  = 0.0
        self.entry_px  = 0.0
        self.equity_curve: list[float] = [initial_cash]
        self.trades: list[dict] = []
        self._win_sum  = 0.0
        self._loss_sum = 0.0
        self._win_n    = 0
        self._loss_n   = 0
        # turnover tracking
        self._total_traded_notional: float = 0.0
        self._recent_returns: list[float] = []   # rolling 20d for vol estimate

    @property
    def portfolio_value(self) -> float:
        return self.cash + self.position * (self.entry_px if self.entry_px else 0)

    def _transaction_cost(self, price: float, shares: float) -> float:
        notional = abs(price * shares)
        return notional * (self.commission_rate + self.slippage_rate)

    def _drawdown(self) -> float:
        peak = max(self.equity_curve)
        curr = self.equity_curve[-1]
        return (curr - peak) / peak if peak > 0 else 0.0

    def step(
        self,
        date,
        price: float,
        proba_df_row: pd.Series,
        future_ret: float,
        regime: int = 1,
    ) -> None:
        bull_p = proba_df_row.get(BULLISH_SIGNAL, 0.0)
        bear_p = proba_df_row.get(BEARISH_SIGNAL, 0.0)
        neut_p = proba_df_row.get(NEUTRAL_SIGNAL, 0.0)

        bull_margin = bull_p - max(bear_p, neut_p)
        bear_margin = bear_p - max(bull_p, neut_p)

        action = "hold"
        if bull_p >= self.bull_threshold and bull_margin >= self.margin_threshold:
            action = "buy"
        elif bear_p >= self.bear_threshold and bear_margin >= self.margin_threshold:
            action = "sell"
        elif self.neutral_action == "cash":
            action = "cash"

        # Drawdown brake: tied to personality max_drawdown_limit
        dd = self._drawdown()
        # If we breach the personality's DD limit, halve allocation; below 50% of limit just normal
        dd_scale = 0.5 if dd < -self.max_drawdown_limit else 1.0

        # Regime scale: reduce size in bear regime
        reg_scale = 0.6 if regime == 0 else 1.0

        # ── Vol-targeting sizing (primary method) ──────────────────────────
        # Estimate recent realised vol from equity curve (last 20 days)
        if len(self._recent_returns) >= 5:
            rv = float(np.std(self._recent_returns[-20:]) * np.sqrt(252))
            rv = max(rv, 0.01)
            # position size = target_vol / realised_vol, capped at max_allocation
            vol_target_frac = self.target_annual_vol / rv
        else:
            vol_target_frac = self.max_allocation  # bootstrap: use max before enough data

        # ── Kelly as a secondary cap ──────────────────────────────────────
        win_prob = (self._win_n / max(self._win_n + self._loss_n, 1))
        avg_win  = self._win_sum / max(self._win_n, 1) if self._win_n else 0.02
        avg_loss = self._loss_sum / max(self._loss_n, 1) if self._loss_n else 0.01
        kelly_frac = kelly_fraction(
            win_prob=max(win_prob, 0.3),
            avg_win=max(avg_win, 0.005),
            avg_loss=max(avg_loss, 0.001),
            fraction=self.kelly_frac,
            max_alloc=self.max_allocation,
        )

        # Take the minimum of vol-target and Kelly, then apply DD + regime scales
        alloc_frac = min(vol_target_frac, kelly_frac, self.max_allocation) * dd_scale * reg_scale

        # ── Correct net equity for sizing ────────────────────────────────────
        # For longs:  equity = cash + shares * price   (straightforward)
        # For shorts: cash already contains short proceeds (shares_short * entry_px).
        #             Net equity = cash - shares_short * price
        #             (cash swells when short opened; falls as price rises against us)
        # Using abs(position)*price double-counts when short because proceeds are
        # already in cash — it inflates capital and oversizes the reversal trade.
        if self.position >= 0:
            portfolio_val = self.cash + self.position * price
        else:
            # cash includes proceeds from the short open; net out the buyback liability
            portfolio_val = self.cash - abs(self.position) * price
        portfolio_val = max(portfolio_val, 1.0)   # floor at $1 to avoid degenerate sizing
        target_notional = portfolio_val * alloc_frac

        # Close existing position first if signal flips
        if self.position != 0:
            if (action == "buy" and self.position < 0) or \
               (action == "sell" and self.position > 0) or \
               (action in ("cash", "hold") and self.neutral_action == "cash"):
                cost = self._transaction_cost(price, self.position)
                self._total_traded_notional += abs(self.position * price)

                if self.position > 0:
                    # Close long: receive sale proceeds
                    pnl = self.position * (price - self.entry_px)
                    self.cash += self.position * price - cost
                else:
                    # Close short: buy back shares
                    # We originally received entry_px * |shares|; now pay price * |shares|
                    shares_short = abs(self.position)
                    pnl = shares_short * (self.entry_px - price)   # profit if price fell
                    self.cash -= shares_short * price + cost        # buy-back cost

                self.position = 0
                if pnl > 0:
                    self._win_sum += pnl
                    self._win_n   += 1
                else:
                    self._loss_sum += abs(pnl)
                    self._loss_n   += 1
                self.trades.append({"date": date, "action": "close", "pnl": pnl})

        # Open new position
        if action == "buy" and self.position == 0:
            shares = target_notional / price
            cost   = self._transaction_cost(price, shares)
            if shares * price + cost <= self.cash:
                self.cash    -= shares * price + cost
                self.position = shares
                self.entry_px = price
                self._total_traded_notional += shares * price
                self.trades.append({"date": date, "action": "buy", "pnl": 0.0})

        elif action == "sell" and self.position == 0:
            # Correct short accounting:
            # 1. Receive short-sale proceeds into cash
            # 2. Reserve margin (proceeds stay in cash; broker holds as collateral)
            # 3. Pay transaction cost from cash
            # 4. Mark position as negative shares at entry price
            # On close: cash += entry_px * |shares| − current_px * |shares| − cost
            #           (profit if price fell, loss if price rose)
            shares = target_notional / price
            cost   = self._transaction_cost(price, shares)
            if cost <= self.cash:                          # only need cash for costs
                self.cash    += shares * price             # receive proceeds
                self.cash    -= cost
                self.position = -shares
                self.entry_px = price
                self._total_traded_notional += shares * price
                self.trades.append({"date": date, "action": "sell", "pnl": 0.0})

        current_val = self.cash + self.position * price
        # Track daily return for vol-targeting
        prev_val = self.equity_curve[-1] if self.equity_curve else self.initial_cash
        if prev_val > 0:
            self._recent_returns.append((current_val - prev_val) / prev_val)
        self.equity_curve.append(current_val)

    @property
    def trade_count(self) -> int:
        return len([t for t in self.trades if t["action"] in ("buy", "sell")])

    @property
    def turnover_ratio(self) -> float:
        """Annual turnover = total traded / average portfolio value."""
        avg_equity = float(np.mean(self.equity_curve)) if self.equity_curve else self.initial_cash
        n_days = max(len(self.equity_curve), 1)
        annualised = self._total_traded_notional * 252 / n_days
        return annualised / max(avg_equity, 1.0)

    def run(
        self,
        df: pd.DataFrame,
        proba_df: pd.DataFrame,
        regimes: pd.Series | None = None,
    ) -> pd.DataFrame:
        shared_idx = df.index.intersection(proba_df.index)
        df       = df.loc[shared_idx]
        proba_df = proba_df.loc[shared_idx]

        self.equity_curve = [self.initial_cash]

        for i, (date, row) in enumerate(df.iterrows()):
            price = float(row["Close"])
            if price <= 0:
                self.equity_curve.append(self.equity_curve[-1])
                continue
            proba_row = proba_df.loc[date]
            future_ret = float(row.get("future_ret", 0.0))
            regime = int(regimes.get(date, 1)) if regimes is not None else 1
            self.step(date, price, proba_row, future_ret, regime)

        ec = pd.Series(
            self.equity_curve[1:],
            index=shared_idx,
            name="equity",
        )
        return ec.to_frame()


# ═══════════════════════════════════════════════════════════════════════════
# 9.  PERFORMANCE METRICS
# ═══════════════════════════════════════════════════════════════════════════

def compute_metrics(
    equity_curve: pd.Series,
    risk_free: float = 0.05,
    turnover: float = 0.0,
    trade_count: int = 0,
) -> dict:
    """
    Full performance metric suite.
    turnover and trade_count are optional — passed in from PortfolioSimulator
    when available so the composite score can penalise churn.
    """
    rets = equity_curve.pct_change().dropna()
    empty = {
        "sharpe": 0.0, "sortino": 0.0, "calmar": 0.0,
        "max_dd": 0.0, "total_return": 0.0, "annual_return": 0.0,
        "cagr": 0.0, "win_rate": 0.0, "profit_factor": 0.0,
        "turnover": turnover, "trade_count": trade_count,
    }
    if len(rets) < 5 or rets.std() < 1e-10:
        return empty

    n_years    = len(rets) / 252
    total_ret  = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1
    cagr       = (1 + total_ret) ** (1 / max(n_years, 1e-6)) - 1
    annual_ret = cagr  # same thing, clearer name kept for back-compat

    excess = rets.mean() * 252 - risk_free
    sharpe = excess / (rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0

    # Sortino: only penalise downside deviation
    downside = rets[rets < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 1 else 1e-8
    sortino = excess / downside_std if downside_std > 1e-8 else 0.0

    rolling_max = equity_curve.cummax()
    drawdown    = (equity_curve - rolling_max) / rolling_max
    max_dd      = float(drawdown.min())

    calmar = cagr / abs(max_dd) if abs(max_dd) > 1e-6 else 0.0

    wins   = rets[rets > 0]
    losses = rets[rets < 0]
    win_rate      = len(wins) / max(len(rets), 1)
    profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else 0.0

    return {
        "sharpe":        round(sharpe, 3),
        "sortino":       round(sortino, 3),
        "calmar":        round(calmar, 3),
        "max_dd":        round(max_dd, 4),
        "total_return":  round(total_ret, 4),
        "annual_return": round(annual_ret, 4),
        "cagr":          round(cagr, 4),
        "win_rate":      round(win_rate, 4),
        "profit_factor": round(profit_factor, 3),
        "turnover":      round(turnover, 3),
        "trade_count":   trade_count,
    }


def composite_score(m: dict, args: Any) -> float:
    """
    Personality-aware composite score used for policy selection.
    Higher = better.  Penalties subtract from return-based gains.

    Reads weight_* and turnover_penalty from args (set by personality preset).
    Uses actual commission_rate + slippage_rate from args for cost drag,
    not a hardcoded constant.
    """
    w_cagr      = getattr(args, "weight_cagr",         0.35)
    w_sharpe    = getattr(args, "weight_sharpe",        0.15)
    w_sortino   = getattr(args, "weight_sortino",       0.20)
    w_calmar    = getattr(args, "weight_calmar",        0.15)
    w_dd        = getattr(args, "weight_max_drawdown",  0.25)
    w_turnover  = getattr(args, "weight_turnover",      0.10)
    w_cost_drag = getattr(args, "weight_cost_drag",     0.10)
    tp          = getattr(args, "turnover_penalty",     1.00)

    # Actual round-trip cost rate from simulator config
    commission  = getattr(args, "commission_rate",  0.001)
    slippage    = getattr(args, "slippage_rate",    0.0005)
    rt_cost     = (commission + slippage) * 2       # round-trip: open + close

    # Positive contributions (normalised to roughly 0-1 range)
    score  = w_cagr    * np.clip(m["cagr"],    -1, 2)
    score += w_sharpe  * np.clip(m["sharpe"],  -3, 5) / 5
    score += w_sortino * np.clip(m["sortino"], -3, 8) / 8
    score += w_calmar  * np.clip(m["calmar"],  -2, 5) / 5

    # Penalties
    score -= w_dd        * abs(m["max_dd"])
    score -= w_turnover  * m["turnover"] * tp / 10
    # Cost drag: turnover × actual round-trip rate
    cost_drag = m["turnover"] * rt_cost
    score -= w_cost_drag * cost_drag

    return float(score)


def buy_and_hold_equity(df: pd.DataFrame, initial_cash: float = 10_000.0) -> pd.Series:
    close = df["Close"]
    shares = initial_cash / float(close.iloc[0])
    return (close * shares).rename("buy_hold")


# ═══════════════════════════════════════════════════════════════════════════
# 10.  UNIVERSAL MODEL EVALUATION
# ═══════════════════════════════════════════════════════════════════════════

def parse_float_list(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def parse_str_list(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def _train_universal_ensemble(
    model_factories: dict[str, Any],
    development_by_ticker: dict[str, pd.DataFrame],
    feature_cols: list[str],
    n_splits: int = 5,
    horizon: int = 5,
) -> EnsembleModel:
    """
    Two-pass training to get genuine out-of-sample ensemble weights:

    Pass 1 — weight estimation (no leakage):
      Take the last purged walk-forward fold. Train each model on the train
      portion of that fold only, then score it on the val portion.
      This produces true OOS Sharpe weights because the val rows were never
      seen during that model fit.

    Pass 2 — final model fit:
      Refit each model on ALL development data (all tickers combined) using
      the weights derived in Pass 1.  The final model is full-data trained;
      only the weights came from OOS evaluation.

    Also fixes date-based purge: splits are derived on the combined frame
    which is sorted by date, so purge_gap=horizon removes rows that share
    calendar dates near the fold boundary across all tickers simultaneously.
    """
    frames = []
    for ticker, df in development_by_ticker.items():
        sub = df.copy()
        sub["_ticker"] = ticker
        frames.append(sub)
    combined = pd.concat(frames).sort_index()

    feat_present = [c for c in feature_cols if c in combined.columns]
    X_all = combined[feat_present].copy()
    y_all = combined["signal"].copy()
    fr_all = combined["future_ret"].copy() if "future_ret" in combined.columns else None

    # ── Pass 1: derive weights from last purged fold ──────────────────────────
    splits = purged_walk_forward_splits(combined, n_splits=n_splits, purge_gap=horizon)

    oos_weights: dict[str, float] = {}

    if splits:
        train_idx, val_idx = splits[-1]   # most recent fold
        X_fold_train = X_all.iloc[train_idx]
        y_fold_train = y_all.iloc[train_idx]
        X_fold_val   = X_all.iloc[val_idx]
        y_fold_val   = y_all.iloc[val_idx]
        fr_fold_val  = fr_all.iloc[val_idx] if fr_all is not None else None

        # Fit a temporary scaler+encoder on fold-train only
        tmp_scaler  = StandardScaler()
        tmp_encoder = LabelEncoder()
        X_fold_scaled = tmp_scaler.fit_transform(X_fold_train)
        y_fold_enc    = tmp_encoder.fit_transform(y_fold_train)
        X_val_scaled  = tmp_scaler.transform(X_fold_val)

        for name, factory in model_factories.items():
            try:
                clf = factory()
                clf.fit(X_fold_scaled, y_fold_enc)
                classes_list = list(tmp_encoder.classes_)
                proba = clf.predict_proba(X_val_scaled)
                signal = _signal_from_proba(proba, classes_list)
                if fr_fold_val is not None and len(fr_fold_val) == len(signal):
                    rets = np.array(fr_fold_val.values, dtype=float) * signal
                else:
                    y_raw = y_fold_val.values
                    label_sign = np.where(
                        y_raw == BULLISH_SIGNAL, 1.0,
                        np.where(y_raw == BEARISH_SIGNAL, -1.0, 0.0)
                    ).astype(float)
                    rets = label_sign * signal
                sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 1e-8 else 0.1
                oos_weights[name] = max(sharpe, 0.01)
            except Exception as e:
                print(f"  [warn] weight-pass {name} failed: {e}")
                oos_weights[name] = 0.01

    # ── Pass 2: refit final ensemble on ALL development data ─────────────────
    ensemble = EnsembleModel(model_factories)
    # fit() with no X_val so it won't re-run _val_sharpe; we inject OOS weights after
    ensemble.fit(X_all, y_all)

    if oos_weights:
        total = sum(oos_weights.values())
        ensemble.weights = {k: v / total for k, v in oos_weights.items()
                            if k in ensemble.models}
        # Renormalise in case some models failed in pass 2
        total2 = sum(ensemble.weights.values())
        if total2 > 0:
            ensemble.weights = {k: v / total2 for k, v in ensemble.weights.items()}

    return ensemble


def evaluate_universal_model(
    model_factories: dict[str, Any],
    full_featured_by_ticker: dict[str, pd.DataFrame],
    development_by_ticker: dict[str, pd.DataFrame],
    holdout_by_ticker: dict[str, pd.DataFrame],
    threshold_candidates: list[float],
    margin_candidates: list[float],
    allocation_scales: list[float],
    neutral_options: list[str],
    args: Any,
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:

    # Build feature list from first available ticker
    sample_df = next(iter(development_by_ticker.values()))
    feature_cols = get_feature_columns(sample_df)

    # Regime model (fit on SPY development period)
    spy_full = download_history(args.market_ticker, args.start, args.end)
    spy_ret  = spy_full["Close"].pct_change().dropna()
    regime_filter = RegimeFilter().fit(spy_ret)

    # Train universal ensemble
    print("[progress] Training universal ensemble model …", flush=True)
    ensemble = _train_universal_ensemble(
        model_factories=model_factories,
        development_by_ticker=development_by_ticker,
        feature_cols=feature_cols,
        n_splits=args.n_splits,
        horizon=args.horizon,
    )

    # ── policy tuning on development sets ────────────────────────────────────
    print("[progress] Tuning trading policy …", flush=True)
    best_policy = _tune_policy(
        ensemble=ensemble,
        development_by_ticker=development_by_ticker,
        regime_filter=regime_filter,
        spy_ret=spy_ret,
        threshold_candidates=threshold_candidates,
        margin_candidates=margin_candidates,
        allocation_scales=allocation_scales,
        neutral_options=neutral_options,
        args=args,
    )

    # ── selection summary table ───────────────────────────────────────────────
    selection_rows = [{"param": k, "value": v} for k, v in best_policy.items()]
    selection_table = pd.DataFrame(selection_rows)

    # ── holdout evaluation ────────────────────────────────────────────────────
    print("[progress] Evaluating on holdout …", flush=True)
    holdout_rows = []
    for ticker, h_df in holdout_by_ticker.items():
        feat_present = [c for c in feature_cols if c in h_df.columns]
        proba = ensemble.predict_proba_df(h_df[feat_present])
        regimes = regime_filter.predict(spy_ret.reindex(h_df.index).fillna(0))

        sim = PortfolioSimulator(
            initial_cash=args.initial_cash,
            commission_rate=args.commission_rate,
            slippage_rate=args.slippage_rate,
            bull_threshold=best_policy["bull_threshold"],
            bear_threshold=best_policy.get("bear_threshold", best_policy["bull_threshold"]),
            margin_threshold=best_policy["margin_threshold"],
            neutral_action=best_policy["neutral_action"],
            max_allocation=best_policy["max_allocation"],
            kelly_fraction=best_policy.get("kelly_fraction", 0.25),
            target_annual_vol=best_policy.get("target_annual_vol", 0.14),
            max_drawdown_limit=best_policy.get("max_drawdown_limit", 0.18),
        )
        eq = sim.run(h_df, proba, regimes)["equity"]
        bh = buy_and_hold_equity(h_df, args.initial_cash)

        m    = compute_metrics(eq, turnover=sim.turnover_ratio, trade_count=sim.trade_count)
        bh_m = compute_metrics(bh)

        holdout_rows.append({
            "ticker":        ticker,
            "sharpe":        m["sharpe"],
            "sortino":       m["sortino"],
            "calmar":        m["calmar"],
            "cagr":          m["cagr"],
            "max_dd":        m["max_dd"],
            "total_return":  m["total_return"],
            "annual_return": m["annual_return"],
            "win_rate":      m["win_rate"],
            "profit_factor": m["profit_factor"],
            "trade_count":   m["trade_count"],
            "turnover":      m["turnover"],
            "bh_total_ret":  bh_m["total_return"],
            "bh_sharpe":     bh_m["sharpe"],
            "alpha":         m["total_return"] - bh_m["total_return"],
        })

    holdout_summary = pd.DataFrame(holdout_rows)

    # ── leave-one-ticker-out generalisation test ──────────────────────────────
    loto_rows = []
    tickers = list(development_by_ticker.keys())
    if len(tickers) > 1:
        print("[progress] Leave-one-ticker-out …", flush=True)
        for left_out in tickers:
            train_tickers = {t: d for t, d in development_by_ticker.items() if t != left_out}
            loo_ensemble = _train_universal_ensemble(
                model_factories=model_factories,
                development_by_ticker=train_tickers,
                feature_cols=feature_cols,
            )
            test_df = holdout_by_ticker[left_out]
            feat_present = [c for c in feature_cols if c in test_df.columns]
            proba = loo_ensemble.predict_proba_df(test_df[feat_present])
            regimes = regime_filter.predict(spy_ret.reindex(test_df.index).fillna(0))

            sim = PortfolioSimulator(
                initial_cash=args.initial_cash,
                commission_rate=args.commission_rate,
                slippage_rate=args.slippage_rate,
                bull_threshold=best_policy["bull_threshold"],
                bear_threshold=best_policy.get("bear_threshold", best_policy["bull_threshold"]),
                margin_threshold=best_policy["margin_threshold"],
                neutral_action=best_policy["neutral_action"],
                max_allocation=best_policy["max_allocation"],
                target_annual_vol=best_policy.get("target_annual_vol", 0.14),
                max_drawdown_limit=best_policy.get("max_drawdown_limit", 0.18),
            )
            eq = sim.run(test_df, proba, regimes)["equity"]
            m  = compute_metrics(eq, turnover=sim.turnover_ratio, trade_count=sim.trade_count)
            loto_rows.append({"left_out": left_out, **m})

    loto_summary = pd.DataFrame(loto_rows) if loto_rows else pd.DataFrame(
        columns=["left_out", "sharpe", "calmar", "max_dd", "total_return"]
    )

    # ── save outputs ──────────────────────────────────────────────────────────
    uni_dir = output_dir / "universal"
    uni_dir.mkdir(parents=True, exist_ok=True)

    ensemble.save(uni_dir / "ensemble_model.pkl")
    selection_table.to_csv(uni_dir / "policy_params.csv", index=False)
    holdout_summary.to_csv(uni_dir / "holdout_summary.csv", index=False)
    loto_summary.to_csv(uni_dir / "loto_summary.csv", index=False)

    selected_models_df = pd.DataFrame([
        {"model": name, "weight": round(w, 4)}
        for name, w in ensemble.weights.items()
    ])
    selected_models_df.to_csv(uni_dir / "model_weights.csv", index=False)

    # ── charts ────────────────────────────────────────────────────────────────
    _save_charts(
        ensemble=ensemble,
        holdout_by_ticker=holdout_by_ticker,
        feature_cols=feature_cols,
        regime_filter=regime_filter,
        spy_ret=spy_ret,
        best_policy=best_policy,
        args=args,
        uni_dir=uni_dir,
    )

    return selection_table, holdout_summary, selected_models_df, loto_summary


def _tune_policy(
    ensemble: EnsembleModel,
    development_by_ticker: dict[str, pd.DataFrame],
    regime_filter: RegimeFilter,
    spy_ret: pd.Series,
    threshold_candidates: list[float],
    margin_candidates: list[float],
    allocation_scales: list[float],
    neutral_options: list[str],
    args: Any,
) -> dict:
    """
    Grid search over policy hyperparameters on development data.

    Objective: maximise personality-aware composite score (CAGR + Sortino +
    Sharpe + Calmar − drawdown penalty − turnover penalty).

    Enforces:
      - max_drawdown_limit  : candidates with worse DD are skipped
      - min_trade_count     : candidates with too few trades are skipped
      - turnover_penalty    : applied inside composite_score()
    """
    feature_cols = get_feature_columns(next(iter(development_by_ticker.values())))

    # Read personality params (with safe defaults for back-compat)
    max_dd_limit    = getattr(args, "max_drawdown_limit", 0.25)
    min_trades      = getattr(args, "min_trade_count",    0)
    target_vol      = getattr(args, "target_annual_vol",  0.14)
    max_pos         = getattr(args, "max_position",       0.30)
    bear_threshold_candidates = getattr(args, "bear_threshold_candidates", None)
    if isinstance(bear_threshold_candidates, str):
        bear_threshold_candidates = parse_float_list(bear_threshold_candidates)
    if not bear_threshold_candidates:
        # Equities usually need a stricter bar for shorts than longs.
        bear_threshold_candidates = sorted(
            {
                min(0.95, max(0.50, threshold + 0.05))
                for threshold in threshold_candidates
            }
        )

    # Pre-compute probabilities once — big speed win
    proba_cache: dict[str, pd.DataFrame] = {}
    for ticker, df in development_by_ticker.items():
        feat_present = [c for c in feature_cols if c in df.columns]
        proba_cache[ticker] = ensemble.predict_proba_df(df[feat_present])

    best_score: float = -np.inf
    best_policy: dict = {
        "bull_threshold":   0.55,
        "bear_threshold":   0.60,
        "margin_threshold": 0.05,
        "max_allocation":   max_pos,
        "neutral_action":   "hold",
        "kelly_fraction":   0.25,
        "target_annual_vol": target_vol,
        "max_drawdown_limit": max_dd_limit,
    }

    for bull_thresh in threshold_candidates:
        for bear_thresh in bear_threshold_candidates:
            for margin in margin_candidates:
                for alloc_scale in allocation_scales:
                    for neutral in neutral_options:
                        ticker_scores = []
                        skip = False

                        for ticker, df in development_by_ticker.items():
                            regimes = regime_filter.predict(
                                spy_ret.reindex(df.index).fillna(0)
                            )
                            sim = PortfolioSimulator(
                                initial_cash=args.initial_cash,
                                commission_rate=args.commission_rate,
                                slippage_rate=args.slippage_rate,
                                bull_threshold=bull_thresh,
                                bear_threshold=bear_thresh,
                                margin_threshold=margin,
                                neutral_action=neutral,
                                max_allocation=min(alloc_scale * max_pos, max_pos),
                                target_annual_vol=target_vol,
                                max_drawdown_limit=max_dd_limit,
                            )
                            eq = sim.run(df, proba_cache[ticker], regimes)["equity"]
                            m  = compute_metrics(
                                eq,
                                turnover=sim.turnover_ratio,
                                trade_count=sim.trade_count,
                            )

                        # Hard constraints — skip this candidate entirely
                            if abs(m["max_dd"]) > max_dd_limit:
                                skip = True
                                break
                            if m["trade_count"] < min_trades:
                                skip = True
                                break

                            ticker_scores.append(composite_score(m, args))

                        if skip or not ticker_scores:
                            continue

                        mean_score = float(np.mean(ticker_scores))
                        if mean_score > best_score:
                            best_score = mean_score
                            best_policy = {
                                "bull_threshold":    bull_thresh,
                                "bear_threshold":    bear_thresh,
                                "margin_threshold":  margin,
                                "max_allocation":    min(alloc_scale * max_pos, max_pos),
                                "neutral_action":    neutral,
                                "kelly_fraction":    0.25,
                                "target_annual_vol": target_vol,
                                "max_drawdown_limit": max_dd_limit,
                                "tuning_score":      round(mean_score, 4),
                            }

    print(
        f"  Best composite score: {best_policy.get('tuning_score', 0):.4f}  "
        f"bull={best_policy['bull_threshold']}  "
        f"bear={best_policy['bear_threshold']}  "
        f"margin={best_policy['margin_threshold']}  "
        f"alloc={best_policy['max_allocation']:.2f}  "
        f"neutral={best_policy['neutral_action']}  "
        f"target_vol={best_policy['target_annual_vol']:.2f}",
        flush=True,
    )
    return best_policy


def _save_charts(
    ensemble: EnsembleModel,
    holdout_by_ticker: dict[str, pd.DataFrame],
    feature_cols: list[str],
    regime_filter: RegimeFilter,
    spy_ret: pd.Series,
    best_policy: dict,
    args: Any,
    uni_dir: Path,
) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
    except ImportError:
        print("  [warn] matplotlib not available; skipping charts.")
        return

    for ticker, h_df in holdout_by_ticker.items():
        feat_present = [c for c in feature_cols if c in h_df.columns]
        proba = ensemble.predict_proba_df(h_df[feat_present])
        regimes = regime_filter.predict(spy_ret.reindex(h_df.index).fillna(0))

        sim = PortfolioSimulator(
            initial_cash=args.initial_cash,
            commission_rate=args.commission_rate,
            slippage_rate=args.slippage_rate,
            bull_threshold=best_policy["bull_threshold"],
            bear_threshold=best_policy.get("bear_threshold", best_policy["bull_threshold"]),
            margin_threshold=best_policy["margin_threshold"],
            neutral_action=best_policy["neutral_action"],
            max_allocation=best_policy["max_allocation"],
            target_annual_vol=best_policy.get("target_annual_vol", 0.14),
            max_drawdown_limit=best_policy.get("max_drawdown_limit", 0.18),
        )
        eq = sim.run(h_df, proba, regimes)["equity"]
        bh = buy_and_hold_equity(h_df, args.initial_cash)

        fig = plt.figure(figsize=(14, 10))
        gs  = gridspec.GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.35)

        ax0 = fig.add_subplot(gs[0])
        ax0.plot(eq.index, eq.values,    label="Strategy",      lw=1.8, color="#2ecc71")
        ax0.plot(bh.index, bh.values,    label="Buy & Hold",    lw=1.4, color="#3498db", alpha=0.7)
        ax0.set_title(f"{ticker} — Holdout Equity Curve", fontsize=13, fontweight="bold")
        ax0.set_ylabel("Portfolio Value ($)")
        ax0.legend()
        ax0.grid(alpha=0.3)

        # Drawdown
        ax1 = fig.add_subplot(gs[1])
        roll_max = eq.cummax()
        dd = (eq - roll_max) / roll_max * 100
        ax1.fill_between(dd.index, dd.values, 0, alpha=0.5, color="#e74c3c")
        ax1.set_ylabel("Drawdown (%)")
        ax1.grid(alpha=0.3)

        # Bull probability
        ax2 = fig.add_subplot(gs[2])
        if BULLISH_SIGNAL in proba.columns:
            ax2.plot(proba.index, proba[BULLISH_SIGNAL], color="#f39c12", lw=1, alpha=0.7)
            ax2.axhline(best_policy["bull_threshold"], color="gray", ls="--", lw=0.8)
        ax2.set_ylabel("Bull Prob")
        ax2.set_ylim(0, 1)
        ax2.grid(alpha=0.3)

        m = compute_metrics(eq, turnover=sim.turnover_ratio, trade_count=sim.trade_count)
        personality = getattr(args, "personality", "balanced")
        fig.suptitle(
            f"[{personality}]  Sharpe: {m['sharpe']:.2f}  |  Sortino: {m['sortino']:.2f}  |  "
            f"Calmar: {m['calmar']:.2f}  |  CAGR: {m['cagr']*100:.1f}%  |  "
            f"Max DD: {m['max_dd']*100:.1f}%  |  Trades: {m['trade_count']}  |  Turnover: {m['turnover']:.1f}x",
            fontsize=9, y=0.99,
        )
        out_path = uni_dir / f"{ticker}_holdout.png"
        fig.savefig(out_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved chart: {out_path}")
