import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.trading_journal_model import VMTradingJournalEntry

MONEY_QUANT = Decimal("0.01")


def _to_decimal_money(value) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise HTTPException(status_code=400, detail="Invalid pnl_amount")
    return parsed.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _to_user_uuid(user_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid user id in token")


def _normalize_symbol(symbol: str) -> str:
    clean = str(symbol or "").strip().upper()
    if not clean:
        raise HTTPException(status_code=400, detail="Symbol is required")
    if len(clean) > 10:
        raise HTTPException(status_code=400, detail="Symbol too long")
    return clean


def _normalize_note(note: str | None) -> str:
    clean = str(note or "").strip()
    return clean or "No notes added."


def _serialize_entry(entry: VMTradingJournalEntry):
    return {
        "entry_id": entry.entry_id,
        "symbol": entry.symbol,
        "entry_date": entry.entry_date,
        "pnl_amount": float(entry.pnl_amount),
        "note": entry.note,
        "linked_order_id": entry.linked_order_id,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
    }


class TradingJournalService:
    @staticmethod
    async def list_entries(db: AsyncSession, user_id: str, limit: int = 50, offset: int = 0):
        user_uuid = _to_user_uuid(user_id)
        rows = (
            await db.execute(
                select(VMTradingJournalEntry)
                .where(VMTradingJournalEntry.user_id == user_uuid)
                .order_by(
                    VMTradingJournalEntry.entry_date.desc(),
                    VMTradingJournalEntry.created_at.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return {"items": [_serialize_entry(entry) for entry in rows]}

    @staticmethod
    async def create_entry(db: AsyncSession, user_id: str, payload):
        user_uuid = _to_user_uuid(user_id)

        entry = VMTradingJournalEntry(
            user_id=user_uuid,
            symbol=_normalize_symbol(payload.symbol),
            entry_date=payload.entry_date,
            pnl_amount=_to_decimal_money(payload.pnl_amount),
            note=_normalize_note(payload.note),
            linked_order_id=payload.linked_order_id,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return _serialize_entry(entry)

    @staticmethod
    async def update_entry(db: AsyncSession, user_id: str, entry_id: uuid.UUID, payload):
        user_uuid = _to_user_uuid(user_id)

        entry = (
            await db.execute(
                select(VMTradingJournalEntry).where(
                    VMTradingJournalEntry.entry_id == entry_id,
                    VMTradingJournalEntry.user_id == user_uuid,
                )
            )
        ).scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Journal entry not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return _serialize_entry(entry)

        if "symbol" in updates:
            entry.symbol = _normalize_symbol(updates["symbol"])
        if "entry_date" in updates:
            entry.entry_date = updates["entry_date"]
        if "pnl_amount" in updates:
            entry.pnl_amount = _to_decimal_money(updates["pnl_amount"])
        if "note" in updates:
            entry.note = _normalize_note(updates["note"])
        if "linked_order_id" in updates:
            entry.linked_order_id = updates["linked_order_id"]

        await db.commit()
        await db.refresh(entry)
        return _serialize_entry(entry)

    @staticmethod
    async def delete_entry(db: AsyncSession, user_id: str, entry_id: uuid.UUID):
        user_uuid = _to_user_uuid(user_id)

        entry = (
            await db.execute(
                select(VMTradingJournalEntry).where(
                    VMTradingJournalEntry.entry_id == entry_id,
                    VMTradingJournalEntry.user_id == user_uuid,
                )
            )
        ).scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Journal entry not found")

        await db.delete(entry)
        await db.commit()
        return {"deleted": True, "entry_id": entry_id}
