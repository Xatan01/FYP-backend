import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.virtual_market_model import (
    VMPriceDaily,
    VMStock,
    VMUserOrder,
    VMUserPosition,
    VMUserStockUnlock,
    VMUserWallet,
)
from services.twelvedata import fetch_latest_daily_ohlcv

QTY_QUANT = Decimal("0.000001")
PRICE_QUANT = Decimal("0.0001")
MONEY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.01")


def _to_decimal(value, quant: Decimal) -> Decimal:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid numeric value")
    return decimal_value.quantize(quant, rounding=ROUND_HALF_UP)


def _to_float(value):
    if value is None:
        return None
    return float(value)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class VirtualMarketService:
    @staticmethod
    def _to_user_uuid(user_id: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid user id in token")

    @staticmethod
    def _initial_cash() -> Decimal:
        raw = (os.getenv("VM_INITIAL_CASH") or "10000").strip()
        return _to_decimal(raw, MONEY_QUANT)

    @staticmethod
    def _fee_rate() -> Decimal:
        raw = (os.getenv("VM_FEE_RATE") or "0").strip()
        try:
            rate = Decimal(raw)
        except (InvalidOperation, ValueError, TypeError):
            rate = Decimal("0")
        if rate < 0:
            rate = Decimal("0")
        return rate

    @staticmethod
    def _default_unlock_count() -> int:
        raw = (os.getenv("VM_DEFAULT_UNLOCK_COUNT") or "2").strip()
        try:
            count = int(raw)
        except ValueError:
            return 2
        return max(0, count)

    @staticmethod
    def _default_unlock_symbols() -> list[str]:
        raw = (os.getenv("VM_DEFAULT_UNLOCKED_SYMBOLS") or "").strip()
        if not raw:
            return []
        items = [symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()]
        return list(dict.fromkeys(items))

    @staticmethod
    async def _ensure_wallet(db: AsyncSession, user_uuid: uuid.UUID, lock: bool = False):
        stmt = select(VMUserWallet).where(VMUserWallet.user_id == user_uuid)
        if lock:
            stmt = stmt.with_for_update()
        wallet = (await db.execute(stmt)).scalar_one_or_none()
        created = False
        if wallet is None:
            wallet = VMUserWallet(
                user_id=user_uuid,
                cash_balance=VirtualMarketService._initial_cash(),
                updated_at=_now_utc(),
            )
            db.add(wallet)
            await db.flush()
            created = True
        return wallet, created

    @staticmethod
    async def _latest_prices_map(db: AsyncSession, stock_ids: list[int]):
        if not stock_ids:
            return {}
        latest_subquery = (
            select(
                VMPriceDaily.stock_id.label("stock_id"),
                func.max(VMPriceDaily.price_date).label("max_price_date"),
            )
            .where(VMPriceDaily.stock_id.in_(stock_ids))
            .group_by(VMPriceDaily.stock_id)
            .subquery()
        )
        rows = (
            await db.execute(
                select(VMPriceDaily).join(
                    latest_subquery,
                    and_(
                        VMPriceDaily.stock_id == latest_subquery.c.stock_id,
                        VMPriceDaily.price_date == latest_subquery.c.max_price_date,
                    ),
                )
            )
        ).scalars().all()
        return {int(row.stock_id): row for row in rows}

    @staticmethod
    async def _get_active_stock_by_symbol(db: AsyncSession, symbol: str):
        clean_symbol = (symbol or "").strip().upper()
        if not clean_symbol:
            raise HTTPException(status_code=400, detail="Symbol is required")

        stock = (
            await db.execute(
                select(VMStock).where(
                    VMStock.symbol == clean_symbol,
                    VMStock.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not stock:
            raise HTTPException(status_code=404, detail=f"Unsupported stock symbol '{clean_symbol}'")
        return stock

    @staticmethod
    async def _get_latest_price_or_409(db: AsyncSession, stock_id: int):
        latest_price = (
            await db.execute(
                select(VMPriceDaily)
                .where(VMPriceDaily.stock_id == stock_id)
                .order_by(VMPriceDaily.price_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not latest_price:
            raise HTTPException(
                status_code=409,
                detail="No stored market price found for this stock",
            )
        return latest_price

    @staticmethod
    async def bootstrap(db: AsyncSession, user_id: str):
        user_uuid = VirtualMarketService._to_user_uuid(user_id)
        wallet, _ = await VirtualMarketService._ensure_wallet(db, user_uuid, lock=False)

        active_stocks = (
            await db.execute(
                select(VMStock).where(VMStock.is_active.is_(True)).order_by(VMStock.symbol.asc())
            )
        ).scalars().all()
        if not active_stocks:
            raise HTTPException(status_code=409, detail="No active stocks configured")

        default_symbols = set(VirtualMarketService._default_unlock_symbols())
        if default_symbols:
            target_stocks = [stock for stock in active_stocks if stock.symbol in default_symbols]
        else:
            unlock_count = VirtualMarketService._default_unlock_count()
            target_stocks = active_stocks[:unlock_count]

        existing_unlocks = (
            await db.execute(
                select(VMUserStockUnlock.stock_id).where(VMUserStockUnlock.user_id == user_uuid)
            )
        ).scalars().all()
        existing_unlock_ids = {int(stock_id) for stock_id in existing_unlocks}

        for stock in target_stocks:
            if int(stock.stock_id) in existing_unlock_ids:
                continue
            db.add(
                VMUserStockUnlock(
                    user_id=user_uuid,
                    stock_id=stock.stock_id,
                    unlock_reason="default_bootstrap",
                )
            )

        await db.commit()

        unlocked_symbols = (
            await db.execute(
                select(VMStock.symbol)
                .join(VMUserStockUnlock, VMUserStockUnlock.stock_id == VMStock.stock_id)
                .where(VMUserStockUnlock.user_id == user_uuid)
                .order_by(VMStock.symbol.asc())
            )
        ).scalars().all()

        return {
            "user_id": user_uuid,
            "cash_balance": _to_float(wallet.cash_balance),
            "unlocked_symbols": list(unlocked_symbols),
        }

    @staticmethod
    async def list_stocks(db: AsyncSession, user_id: str):
        user_uuid = VirtualMarketService._to_user_uuid(user_id)
        stocks = (
            await db.execute(
                select(VMStock).where(VMStock.is_active.is_(True)).order_by(VMStock.symbol.asc())
            )
        ).scalars().all()

        stock_ids = [int(stock.stock_id) for stock in stocks]
        latest_prices = await VirtualMarketService._latest_prices_map(db, stock_ids)
        unlocked_rows = (
            await db.execute(
                select(VMUserStockUnlock.stock_id).where(VMUserStockUnlock.user_id == user_uuid)
            )
        ).scalars().all()
        unlocked_ids = {int(stock_id) for stock_id in unlocked_rows}

        items = []
        for stock in stocks:
            latest = latest_prices.get(int(stock.stock_id))
            items.append(
                {
                    "stock_id": int(stock.stock_id),
                    "symbol": stock.symbol,
                    "name": stock.name,
                    "exchange": stock.exchange,
                    "currency": stock.currency,
                    "is_unlocked": int(stock.stock_id) in unlocked_ids,
                    "latest_price": _to_float(latest.close) if latest else None,
                    "latest_price_date": latest.price_date if latest else None,
                }
            )

        return {
            "items": items,
            "updated_at": _now_utc(),
        }

    @staticmethod
    async def get_portfolio(db: AsyncSession, user_id: str):
        user_uuid = VirtualMarketService._to_user_uuid(user_id)
        wallet = (
            await db.execute(select(VMUserWallet).where(VMUserWallet.user_id == user_uuid))
        ).scalar_one_or_none()

        if not wallet:
            wallet = VMUserWallet(
                user_id=user_uuid,
                cash_balance=VirtualMarketService._initial_cash(),
                updated_at=_now_utc(),
            )
            db.add(wallet)
            await db.commit()

        positions = (
            await db.execute(
                select(VMUserPosition)
                .where(
                    VMUserPosition.user_id == user_uuid,
                    VMUserPosition.quantity > 0,
                )
                .order_by(VMUserPosition.stock_id.asc())
            )
        ).scalars().all()

        stock_ids = [int(position.stock_id) for position in positions]
        stocks_by_id = {}
        if stock_ids:
            stock_rows = (
                await db.execute(select(VMStock).where(VMStock.stock_id.in_(stock_ids)))
            ).scalars().all()
            stocks_by_id = {int(stock.stock_id): stock for stock in stock_rows}
        latest_prices = await VirtualMarketService._latest_prices_map(db, stock_ids)

        total_market_value = Decimal("0")
        total_cost_basis = Decimal("0")
        total_unrealized = Decimal("0")
        position_items = []
        for position in positions:
            stock_id = int(position.stock_id)
            stock = stocks_by_id.get(stock_id)
            latest = latest_prices.get(stock_id)

            quantity = _to_decimal(position.quantity, QTY_QUANT)
            avg_cost = _to_decimal(position.avg_cost, PRICE_QUANT)
            cost_basis = _to_decimal(quantity * avg_cost, MONEY_QUANT)

            current_price = _to_decimal(latest.close, PRICE_QUANT) if latest else None
            current_value = _to_decimal(quantity * current_price, MONEY_QUANT) if current_price else Decimal("0")
            unrealized = _to_decimal(current_value - cost_basis, MONEY_QUANT)

            total_market_value += current_value
            total_cost_basis += cost_basis
            total_unrealized += unrealized

            position_items.append(
                {
                    "stock_id": stock_id,
                    "symbol": stock.symbol if stock else f"#{stock_id}",
                    "name": stock.name if stock else "Unknown",
                    "quantity": _to_float(quantity),
                    "avg_cost": _to_float(avg_cost),
                    "current_price": _to_float(current_price) if current_price else None,
                    "current_value": _to_float(current_value),
                    "cost_basis": _to_float(cost_basis),
                    "unrealized_pnl": _to_float(unrealized),
                    "profit_loss": _to_float(unrealized),
                    "profit_loss_status": (
                        "gain"
                        if unrealized > 0
                        else "loss"
                        if unrealized < 0
                        else "flat"
                    ),
                }
            )

        cash_balance = _to_decimal(wallet.cash_balance, MONEY_QUANT)
        total_equity = _to_decimal(cash_balance + total_market_value, MONEY_QUANT)
        total_unrealized_percent = Decimal("0")
        if total_cost_basis > 0:
            total_unrealized_percent = _to_decimal(
                (total_unrealized / total_cost_basis) * Decimal("100"),
                PERCENT_QUANT,
            )

        return {
            "user_id": user_uuid,
            "cash_balance": _to_float(cash_balance),
            "total_market_value": _to_float(total_market_value),
            "total_cost_basis": _to_float(total_cost_basis),
            "total_equity": _to_float(total_equity),
            "total_unrealized_pnl": _to_float(total_unrealized),
            "total_unrealized_pnl_percent": _to_float(total_unrealized_percent),
            "positions": position_items,
            "updated_at": _now_utc(),
        }

    @staticmethod
    async def _build_order_response(
        db: AsyncSession,
        user_uuid: uuid.UUID,
        order: VMUserOrder,
        symbol: str,
    ):
        wallet = (
            await db.execute(select(VMUserWallet).where(VMUserWallet.user_id == user_uuid))
        ).scalar_one_or_none()
        position = (
            await db.execute(
                select(VMUserPosition).where(
                    VMUserPosition.user_id == user_uuid,
                    VMUserPosition.stock_id == order.stock_id,
                )
            )
        ).scalar_one_or_none()

        cash_balance = _to_decimal(wallet.cash_balance, MONEY_QUANT) if wallet else Decimal("0")
        position_quantity = (
            _to_decimal(position.quantity, QTY_QUANT) if position else Decimal("0")
        )
        position_avg_cost = _to_decimal(position.avg_cost, PRICE_QUANT) if position else Decimal("0")

        return {
            "order_id": int(order.order_id),
            "symbol": symbol,
            "side": order.side,
            "quantity": _to_float(_to_decimal(order.quantity, QTY_QUANT)),
            "unit_price": _to_float(_to_decimal(order.unit_price, PRICE_QUANT)),
            "gross_amount": _to_float(_to_decimal(order.gross_amount, MONEY_QUANT)),
            "fee_amount": _to_float(_to_decimal(order.fee_amount, MONEY_QUANT)),
            "net_amount": _to_float(_to_decimal(order.net_amount, MONEY_QUANT)),
            "realized_pnl": _to_float(_to_decimal(order.realized_pnl, MONEY_QUANT))
            if order.realized_pnl is not None
            else None,
            "price_date": order.price_date,
            "cash_balance": _to_float(cash_balance),
            "position_quantity": _to_float(position_quantity),
            "position_avg_cost": _to_float(position_avg_cost),
            "created_at": order.created_at,
        }

    @staticmethod
    async def place_order(
        db: AsyncSession,
        user_id: str,
        side: str,
        symbol: str,
        quantity,
        client_order_id: str | None = None,
    ):
        user_uuid = VirtualMarketService._to_user_uuid(user_id)
        side = (side or "").strip().lower()
        if side not in {"buy", "sell"}:
            raise HTTPException(status_code=400, detail="Side must be 'buy' or 'sell'")

        quantity_dec = _to_decimal(quantity, QTY_QUANT)
        if quantity_dec <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")

        stock = await VirtualMarketService._get_active_stock_by_symbol(db, symbol)
        latest_price = await VirtualMarketService._get_latest_price_or_409(db, int(stock.stock_id))
        unit_price = _to_decimal(latest_price.close, PRICE_QUANT)
        gross_amount = _to_decimal(unit_price * quantity_dec, MONEY_QUANT)
        fee_amount = _to_decimal(gross_amount * VirtualMarketService._fee_rate(), MONEY_QUANT)
        net_amount = _to_decimal(
            gross_amount + fee_amount if side == "buy" else gross_amount - fee_amount,
            MONEY_QUANT,
        )
        if net_amount <= 0:
            raise HTTPException(status_code=400, detail="Net amount must be positive")

        unlock = (
            await db.execute(
                select(VMUserStockUnlock).where(
                    VMUserStockUnlock.user_id == user_uuid,
                    VMUserStockUnlock.stock_id == stock.stock_id,
                )
            )
        ).scalar_one_or_none()
        if not unlock:
            raise HTTPException(
                status_code=403,
                detail=f"Stock '{stock.symbol}' is not unlocked for this user",
            )

        if client_order_id:
            duplicate = (
                await db.execute(
                    select(VMUserOrder).where(
                        VMUserOrder.user_id == user_uuid,
                        VMUserOrder.client_order_id == client_order_id,
                    )
                )
            ).scalar_one_or_none()
            if duplicate:
                raise HTTPException(status_code=409, detail="Duplicate client_order_id")

        try:
            wallet, _ = await VirtualMarketService._ensure_wallet(db, user_uuid, lock=True)
            wallet_balance = _to_decimal(wallet.cash_balance, MONEY_QUANT)

            position = (
                await db.execute(
                    select(VMUserPosition)
                    .where(
                        VMUserPosition.user_id == user_uuid,
                        VMUserPosition.stock_id == stock.stock_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()

            old_qty = _to_decimal(position.quantity, QTY_QUANT) if position else Decimal("0")
            old_avg = _to_decimal(position.avg_cost, PRICE_QUANT) if position else Decimal("0")

            realized_pnl = None
            if side == "buy":
                if wallet_balance < net_amount:
                    raise HTTPException(status_code=400, detail="Insufficient cash balance")
                new_qty = _to_decimal(old_qty + quantity_dec, QTY_QUANT)
                new_avg = _to_decimal(
                    ((old_qty * old_avg) + (quantity_dec * unit_price)) / new_qty,
                    PRICE_QUANT,
                )
                if position is None:
                    position = VMUserPosition(
                        user_id=user_uuid,
                        stock_id=stock.stock_id,
                        quantity=new_qty,
                        avg_cost=new_avg,
                        updated_at=_now_utc(),
                    )
                    db.add(position)
                else:
                    position.quantity = new_qty
                    position.avg_cost = new_avg
                    position.updated_at = _now_utc()
                wallet.cash_balance = _to_decimal(wallet_balance - net_amount, MONEY_QUANT)
                wallet.updated_at = _now_utc()
            else:
                if position is None or old_qty < quantity_dec:
                    raise HTTPException(status_code=400, detail="Insufficient shares to sell")
                remaining_qty = _to_decimal(old_qty - quantity_dec, QTY_QUANT)
                wallet.cash_balance = _to_decimal(wallet_balance + net_amount, MONEY_QUANT)
                wallet.updated_at = _now_utc()

                realized_pnl = _to_decimal(
                    ((unit_price - old_avg) * quantity_dec) - fee_amount,
                    MONEY_QUANT,
                )

                position.quantity = remaining_qty
                position.avg_cost = Decimal("0") if remaining_qty == 0 else old_avg
                position.updated_at = _now_utc()

            order = VMUserOrder(
                user_id=user_uuid,
                stock_id=stock.stock_id,
                side=side,
                quantity=quantity_dec,
                unit_price=unit_price,
                gross_amount=gross_amount,
                fee_amount=fee_amount,
                net_amount=net_amount,
                realized_pnl=realized_pnl,
                price_date=latest_price.price_date,
                client_order_id=client_order_id,
            )
            db.add(order)
            await db.flush()
            await db.commit()
            await db.refresh(order)

            return await VirtualMarketService._build_order_response(db, user_uuid, order, stock.symbol)
        except HTTPException:
            await db.rollback()
            raise
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def list_orders(db: AsyncSession, user_id: str, limit: int = 50, offset: int = 0):
        user_uuid = VirtualMarketService._to_user_uuid(user_id)
        rows = (
            await db.execute(
                select(VMUserOrder, VMStock.symbol)
                .join(VMStock, VMStock.stock_id == VMUserOrder.stock_id)
                .where(VMUserOrder.user_id == user_uuid)
                .order_by(VMUserOrder.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()

        items = []
        for order, symbol in rows:
            items.append(
                {
                    "order_id": int(order.order_id),
                    "symbol": symbol,
                    "side": order.side,
                    "quantity": _to_float(_to_decimal(order.quantity, QTY_QUANT)),
                    "unit_price": _to_float(_to_decimal(order.unit_price, PRICE_QUANT)),
                    "gross_amount": _to_float(_to_decimal(order.gross_amount, MONEY_QUANT)),
                    "fee_amount": _to_float(_to_decimal(order.fee_amount, MONEY_QUANT)),
                    "net_amount": _to_float(_to_decimal(order.net_amount, MONEY_QUANT)),
                    "realized_pnl": _to_float(_to_decimal(order.realized_pnl, MONEY_QUANT))
                    if order.realized_pnl is not None
                    else None,
                    "price_date": order.price_date,
                    "cash_balance": None,
                    "position_quantity": None,
                    "position_avg_cost": None,
                    "created_at": order.created_at,
                }
            )
        return {"items": items}

    @staticmethod
    def validate_sync_admin_key(provided_key: str | None):
        expected_key = (os.getenv("VM_SYNC_ADMIN_KEY") or "").strip()
        if not expected_key:
            raise HTTPException(status_code=500, detail="VM_SYNC_ADMIN_KEY is not set")
        if not provided_key or provided_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")

    @staticmethod
    def normalize_symbol_filter(raw_symbols: str | None):
        if not raw_symbols:
            return None
        symbols = [symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()]
        unique_symbols = list(dict.fromkeys(symbols))
        return unique_symbols or None

    @staticmethod
    async def sync_daily_prices(db: AsyncSession, symbols_filter: list[str] | None = None):
        stock_stmt = select(VMStock).where(VMStock.is_active.is_(True))
        if symbols_filter:
            stock_stmt = stock_stmt.where(VMStock.symbol.in_(symbols_filter))
        stocks = (await db.execute(stock_stmt.order_by(VMStock.symbol.asc()))).scalars().all()
        if not stocks:
            raise HTTPException(status_code=404, detail="No active stocks found to sync")

        synced_count = 0
        failed_count = 0
        items = []
        for stock in stocks:
            try:
                candle = fetch_latest_daily_ohlcv(stock.symbol)
                stmt = pg_insert(VMPriceDaily).values(
                    stock_id=stock.stock_id,
                    price_date=candle["price_date"],
                    open=candle["open"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    volume=candle["volume"],
                    source="twelvedata",
                    fetched_at=_now_utc(),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["stock_id", "price_date"],
                    set_={
                        "open": candle["open"],
                        "high": candle["high"],
                        "low": candle["low"],
                        "close": candle["close"],
                        "volume": candle["volume"],
                        "source": "twelvedata",
                        "fetched_at": _now_utc(),
                    },
                )
                await db.execute(stmt)
                synced_count += 1
                items.append(
                    {
                        "symbol": stock.symbol,
                        "status": "synced",
                        "price_date": candle["price_date"],
                        "detail": None,
                    }
                )
            except HTTPException as exc:
                failed_count += 1
                items.append(
                    {
                        "symbol": stock.symbol,
                        "status": "failed",
                        "price_date": None,
                        "detail": str(exc.detail),
                    }
                )
            except Exception as exc:
                failed_count += 1
                items.append(
                    {
                        "symbol": stock.symbol,
                        "status": "failed",
                        "price_date": None,
                        "detail": f"Unexpected error: {exc}",
                    }
                )
        await db.commit()

        return {
            "synced_count": synced_count,
            "failed_count": failed_count,
            "items": items,
        }
