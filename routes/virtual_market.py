from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.virtual_market_schema import (
    BootstrapOut,
    OrderOut,
    OrdersOut,
    PlaceOrderIn,
    PortfolioOut,
    PriceSyncOut,
    StocksOut,
)
from services.database import get_db
from services.virtual_market_service import VirtualMarketService

router = APIRouter(tags=["virtual-market"])


@router.post("/bootstrap", response_model=BootstrapOut)
async def bootstrap_virtual_market(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await VirtualMarketService.bootstrap(db, user["sub"])


@router.get("/stocks", response_model=StocksOut)
async def list_virtual_market_stocks(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await VirtualMarketService.list_stocks(db, user["sub"])


@router.get("/portfolio", response_model=PortfolioOut)
async def get_virtual_market_portfolio(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await VirtualMarketService.get_portfolio(db, user["sub"])


@router.post("/orders/buy", response_model=OrderOut)
async def buy_stock(
    payload: PlaceOrderIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await VirtualMarketService.place_order(
        db=db,
        user_id=user["sub"],
        side="buy",
        symbol=payload.symbol,
        quantity=payload.quantity,
        client_order_id=payload.client_order_id,
    )


@router.post("/orders/sell", response_model=OrderOut)
async def sell_stock(
    payload: PlaceOrderIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await VirtualMarketService.place_order(
        db=db,
        user_id=user["sub"],
        side="sell",
        symbol=payload.symbol,
        quantity=payload.quantity,
        client_order_id=payload.client_order_id,
    )


@router.get("/orders", response_model=OrdersOut)
async def list_order_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await VirtualMarketService.list_orders(db, user["sub"], limit=limit, offset=offset)


@router.post("/admin/sync-daily-prices", response_model=PriceSyncOut)
async def sync_daily_prices(
    symbols: str | None = Query(default=None, description="Comma-separated symbols"),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    db: AsyncSession = Depends(get_db),
):
    VirtualMarketService.validate_sync_admin_key(x_admin_key)
    symbol_filter = VirtualMarketService.normalize_symbol_filter(symbols)
    return await VirtualMarketService.sync_daily_prices(db, symbol_filter)
