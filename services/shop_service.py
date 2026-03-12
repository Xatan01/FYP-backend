import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_model import StockShopCatalogItem, StockShopPurchase
from models.virtual_market_model import VMStock, VMUserStockUnlock, VMUserWallet
from services.virtual_market_service import _to_decimal, _to_float, MONEY_QUANT


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ShopService:
    @staticmethod
    def _to_user_uuid(user_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid user id in token")

    @staticmethod
    def _default_shop_price() -> Decimal:
        raw = (os.getenv("SHOP_DEFAULT_PRICE") or "4.99").strip()
        return _to_decimal(raw, MONEY_QUANT)

    @staticmethod
    def _shop_price_overrides() -> dict[str, Decimal]:
        raw = (os.getenv("SHOP_PRICE_OVERRIDES") or "").strip()
        if not raw:
            return {}

        overrides: dict[str, Decimal] = {}
        for chunk in raw.split(","):
            part = chunk.strip()
            if not part or ":" not in part:
                continue
            symbol, amount = part.split(":", 1)
            clean_symbol = symbol.strip().upper()
            clean_amount = amount.strip()
            if not clean_symbol or not clean_amount:
                continue
            try:
                overrides[clean_symbol] = _to_decimal(clean_amount, MONEY_QUANT)
            except HTTPException:
                continue
        return overrides

    @staticmethod
    async def _ensure_wallet(db: AsyncSession, user_uuid: uuid.UUID):
        wallet = (
            await db.execute(select(VMUserWallet).where(VMUserWallet.user_id == user_uuid))
        ).scalar_one_or_none()
        if wallet:
            return

        initial_cash = _to_decimal((os.getenv("VM_INITIAL_CASH") or "10000").strip(), MONEY_QUANT)
        db.add(
            VMUserWallet(
                user_id=user_uuid,
                cash_balance=initial_cash,
                updated_at=_now_utc(),
            )
        )
        await db.flush()

    @staticmethod
    async def _ensure_catalog(db: AsyncSession):
        active_stocks = (
            await db.execute(
                select(VMStock).where(VMStock.is_active.is_(True)).order_by(VMStock.symbol.asc())
            )
        ).scalars().all()
        if not active_stocks:
            return False

        existing_rows = (await db.execute(select(StockShopCatalogItem.stock_id))).scalars().all()
        existing_stock_ids = {int(stock_id) for stock_id in existing_rows}

        default_price = ShopService._default_shop_price()
        overrides = ShopService._shop_price_overrides()
        changed = False

        for stock in active_stocks:
            stock_id = int(stock.stock_id)
            if stock_id in existing_stock_ids:
                continue
            db.add(
                StockShopCatalogItem(
                    stock_id=stock_id,
                    unlock_price=overrides.get(stock.symbol, default_price),
                    currency="USD",
                    is_active=True,
                    updated_at=_now_utc(),
                )
            )
            changed = True

        if changed:
            await db.flush()
        return changed

    @staticmethod
    def _serialize_purchase(purchase: StockShopPurchase, symbol: str, unlocked: bool = True):
        return {
            "purchase_id": int(purchase.purchase_id),
            "symbol": symbol,
            "amount": _to_float(_to_decimal(purchase.amount, MONEY_QUANT)),
            "currency": purchase.currency,
            "payment_provider": purchase.payment_provider,
            "provider_transaction_id": purchase.provider_transaction_id,
            "payment_status": purchase.payment_status,
            "unlocked": unlocked,
            "purchased_at": purchase.purchased_at,
        }

    @staticmethod
    async def list_catalog(db: AsyncSession, user_id: str):
        user_uuid = ShopService._to_user_uuid(user_id)
        catalog_changed = await ShopService._ensure_catalog(db)

        rows = (
            await db.execute(
                select(StockShopCatalogItem, VMStock)
                .join(VMStock, VMStock.stock_id == StockShopCatalogItem.stock_id)
                .where(
                    StockShopCatalogItem.is_active.is_(True),
                    VMStock.is_active.is_(True),
                )
                .order_by(VMStock.symbol.asc())
            )
        ).all()

        unlocked_rows = (
            await db.execute(
                select(VMUserStockUnlock.stock_id).where(VMUserStockUnlock.user_id == user_uuid)
            )
        ).scalars().all()
        unlocked_ids = {int(stock_id) for stock_id in unlocked_rows}

        if catalog_changed:
            await db.commit()

        items = []
        for shop_item, stock in rows:
            items.append(
                {
                    "stock_id": int(stock.stock_id),
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "unlock_price": _to_float(_to_decimal(shop_item.unlock_price, MONEY_QUANT)),
                    "currency": shop_item.currency,
                    "is_active": bool(shop_item.is_active),
                    "is_unlocked": int(stock.stock_id) in unlocked_ids,
                }
            )

        return {"items": items, "updated_at": _now_utc()}

    @staticmethod
    async def purchase_unlock(
        db: AsyncSession,
        user_id: str,
        symbol: str,
        payment_provider: str,
        provider_transaction_id: str,
        amount,
        currency: str,
        payment_status: str,
    ):
        user_uuid = ShopService._to_user_uuid(user_id)
        await ShopService._ensure_wallet(db, user_uuid)
        await ShopService._ensure_catalog(db)

        clean_provider = str(payment_provider or "").strip().lower()
        clean_txn = str(provider_transaction_id or "").strip()
        clean_status = str(payment_status or "").strip().lower()
        clean_currency = str(currency or "").strip().upper()
        if not clean_provider:
            raise HTTPException(status_code=400, detail="payment_provider is required")
        if not clean_txn:
            raise HTTPException(status_code=400, detail="provider_transaction_id is required")
        if clean_status != "completed":
            raise HTTPException(status_code=400, detail="payment_status must be 'completed'")

        stock = (
            await db.execute(
                select(VMStock).where(
                    VMStock.symbol == str(symbol or "").strip().upper(),
                    VMStock.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not stock:
            raise HTTPException(status_code=404, detail=f"Unsupported stock symbol '{symbol}'")

        catalog_item = (
            await db.execute(
                select(StockShopCatalogItem).where(
                    StockShopCatalogItem.stock_id == stock.stock_id,
                    StockShopCatalogItem.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not catalog_item:
            raise HTTPException(status_code=404, detail=f"Stock '{stock.symbol}' is not available in shop")

        expected_amount = _to_decimal(catalog_item.unlock_price, MONEY_QUANT)
        paid_amount = _to_decimal(amount, MONEY_QUANT)
        expected_currency = str(catalog_item.currency or "USD").strip().upper()

        if clean_currency != expected_currency:
            raise HTTPException(
                status_code=400,
                detail=f"Currency mismatch. Expected {expected_currency}",
            )
        if paid_amount != expected_amount:
            raise HTTPException(
                status_code=400,
                detail=f"Amount mismatch. Expected {expected_amount} {expected_currency}",
            )

        existing_unlock = (
            await db.execute(
                select(VMUserStockUnlock).where(
                    VMUserStockUnlock.user_id == user_uuid,
                    VMUserStockUnlock.stock_id == stock.stock_id,
                )
            )
        ).scalar_one_or_none()
        if existing_unlock:
            raise HTTPException(status_code=409, detail=f"Stock '{stock.symbol}' is already unlocked")

        duplicate_purchase = (
            await db.execute(
                select(StockShopPurchase).where(
                    StockShopPurchase.payment_provider == clean_provider,
                    StockShopPurchase.provider_transaction_id == clean_txn,
                )
            )
        ).scalar_one_or_none()
        if duplicate_purchase:
            if (
                duplicate_purchase.user_id != user_uuid
                or int(duplicate_purchase.stock_id) != int(stock.stock_id)
            ):
                raise HTTPException(status_code=409, detail="provider_transaction_id already used")
            duplicate_unlock = (
                await db.execute(
                    select(VMUserStockUnlock).where(
                        VMUserStockUnlock.user_id == duplicate_purchase.user_id,
                        VMUserStockUnlock.stock_id == duplicate_purchase.stock_id,
                    )
                )
            ).scalar_one_or_none()
            return ShopService._serialize_purchase(
                duplicate_purchase,
                stock.symbol,
                unlocked=bool(duplicate_unlock),
            )

        purchase = StockShopPurchase(
            user_id=user_uuid,
            stock_id=stock.stock_id,
            payment_provider=clean_provider,
            provider_transaction_id=clean_txn,
            amount=paid_amount,
            currency=expected_currency,
            payment_status="completed",
            metadata_json={"source": "profile_shop"},
            purchased_at=_now_utc(),
        )
        db.add(purchase)
        await db.flush()

        db.add(
            VMUserStockUnlock(
                user_id=user_uuid,
                stock_id=stock.stock_id,
                unlock_reason=f"shop_purchase:{purchase.purchase_id}",
            )
        )

        await db.commit()
        await db.refresh(purchase)
        return ShopService._serialize_purchase(purchase, stock.symbol, unlocked=True)
