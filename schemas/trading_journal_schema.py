from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TradingJournalEntryCreateIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    entry_date: date
    pnl_amount: Decimal = Field(default=Decimal("0"))
    note: str = Field(default="No notes added.", max_length=5000)
    linked_order_id: Optional[int] = None


class TradingJournalEntryUpdateIn(BaseModel):
    symbol: Optional[str] = Field(default=None, min_length=1, max_length=10)
    entry_date: Optional[date] = None
    pnl_amount: Optional[Decimal] = None
    note: Optional[str] = Field(default=None, max_length=5000)
    linked_order_id: Optional[int] = None


class TradingJournalEntryOut(BaseModel):
    entry_id: UUID
    symbol: str
    entry_date: date
    pnl_amount: float
    note: str
    linked_order_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class TradingJournalEntriesOut(BaseModel):
    items: list[TradingJournalEntryOut]


class TradingJournalDeleteOut(BaseModel):
    deleted: bool
    entry_id: UUID
