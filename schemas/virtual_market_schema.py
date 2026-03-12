from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BootstrapOut(BaseModel):
    user_id: UUID
    cash_balance: float
    unlocked_symbols: list[str]


class TradableStockOut(BaseModel):
    stock_id: int
    symbol: str
    name: str
    exchange: Optional[str] = None
    currency: str
    is_unlocked: bool
    latest_price: Optional[float] = None
    latest_price_date: Optional[date] = None


class StocksOut(BaseModel):
    items: list[TradableStockOut]
    updated_at: datetime


class PositionOut(BaseModel):
    stock_id: int
    symbol: str
    name: str
    quantity: float
    avg_cost: float
    current_price: Optional[float] = None
    current_value: float
    cost_basis: float
    unrealized_pnl: float
    profit_loss: float
    profit_loss_status: str


class PortfolioOut(BaseModel):
    user_id: UUID
    cash_balance: float
    total_market_value: float
    total_cost_basis: float
    total_equity: float
    total_unrealized_pnl: float
    total_unrealized_pnl_percent: float
    positions: list[PositionOut]
    updated_at: datetime


class PlaceOrderIn(BaseModel):
    symbol: str = Field(min_length=1)
    quantity: Decimal = Field(gt=0)
    client_order_id: Optional[str] = Field(default=None, max_length=128)


class OrderOut(BaseModel):
    order_id: int
    symbol: str
    side: str
    quantity: float
    unit_price: float
    gross_amount: float
    fee_amount: float
    net_amount: float
    realized_pnl: Optional[float] = None
    price_date: date
    cash_balance: Optional[float] = None
    position_quantity: Optional[float] = None
    position_avg_cost: Optional[float] = None
    created_at: datetime


class OrdersOut(BaseModel):
    items: list[OrderOut]


class PriceSyncItemOut(BaseModel):
    symbol: str
    status: str
    price_date: Optional[date] = None
    detail: Optional[str] = None


class PriceSyncOut(BaseModel):
    synced_count: int
    failed_count: int
    items: list[PriceSyncItemOut]
