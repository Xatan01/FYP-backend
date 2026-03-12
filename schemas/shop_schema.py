from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class StockShopCatalogItemOut(BaseModel):
    stock_id: int
    symbol: str
    name: str
    unlock_price: float
    currency: str
    is_active: bool
    is_unlocked: bool


class StockShopCatalogOut(BaseModel):
    items: list[StockShopCatalogItemOut]
    updated_at: datetime


class StockShopPurchaseIn(BaseModel):
    symbol: str = Field(min_length=1)
    payment_provider: str = Field(min_length=1, max_length=32)
    provider_transaction_id: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="USD", min_length=1, max_length=8)
    payment_status: str = Field(default="completed", min_length=1, max_length=16)


class StockShopPurchaseOut(BaseModel):
    purchase_id: int
    symbol: str
    amount: float
    currency: str
    payment_provider: str
    provider_transaction_id: str
    payment_status: str
    unlocked: bool
    purchased_at: datetime
