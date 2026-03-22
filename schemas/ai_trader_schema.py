from datetime import date, datetime

from pydantic import BaseModel, field_validator


class PersonalitySignalOut(BaseModel):
    personality: str
    description: str
    signal: str
    bull_prob: float
    bear_prob: float
    hold_prob: float
    size: float
    regime: int
    regime_label: str
    as_of_date: date
    ticker: str
    bull_threshold: float
    bear_threshold: float
    margin_threshold: float
    max_allocation: float
    target_annual_vol: float
    max_drawdown_limit: float
    kelly_fraction: float
    neutral_action: str

    @field_validator("as_of_date", mode="before")
    @classmethod
    def parse_as_of_date(cls, value):
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                return date.fromisoformat(value)
        return value


class TraderSignalsOut(BaseModel):
    ticker: str
    benchmark_ticker: str
    lookback_days: int
    generated_at: datetime
    model_bundle_updated_at: datetime | None = None
    benchmark_last_date: date | None = None
    items: list[PersonalitySignalOut]
