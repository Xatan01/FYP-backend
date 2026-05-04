"""Compatibility shim for imports from services.trading_system."""

from services.train_universal import (
    BEARISH_SIGNAL,
    BULLISH_SIGNAL,
    EnsembleModel,
    NEUTRAL_SIGNAL,
    RegimeFilter,
    _train_universal_ensemble,
    build_features,
    build_model_factories,
    download_history,
    get_feature_columns,
    split_development_holdout,
)

__all__ = [
    "BEARISH_SIGNAL",
    "BULLISH_SIGNAL",
    "EnsembleModel",
    "NEUTRAL_SIGNAL",
    "RegimeFilter",
    "_train_universal_ensemble",
    "build_features",
    "build_model_factories",
    "download_history",
    "get_feature_columns",
    "split_development_holdout",
]
