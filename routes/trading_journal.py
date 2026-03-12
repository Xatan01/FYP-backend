from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.trading_journal_schema import (
    TradingJournalDeleteOut,
    TradingJournalEntriesOut,
    TradingJournalEntryCreateIn,
    TradingJournalEntryOut,
    TradingJournalEntryUpdateIn,
)
from services.database import get_db
from services.trading_journal_service import TradingJournalService

router = APIRouter(tags=["trading-journal"])


@router.get("/entries", response_model=TradingJournalEntriesOut)
async def list_journal_entries(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await TradingJournalService.list_entries(db, user["sub"], limit=limit, offset=offset)


@router.post("/entries", response_model=TradingJournalEntryOut)
async def create_journal_entry(
    payload: TradingJournalEntryCreateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await TradingJournalService.create_entry(db, user["sub"], payload)


@router.patch("/entries/{entry_id}", response_model=TradingJournalEntryOut)
async def update_journal_entry(
    entry_id: UUID,
    payload: TradingJournalEntryUpdateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await TradingJournalService.update_entry(db, user["sub"], entry_id, payload)


@router.delete("/entries/{entry_id}", response_model=TradingJournalDeleteOut)
async def delete_journal_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await TradingJournalService.delete_entry(db, user["sub"], entry_id)
