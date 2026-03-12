from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from routes.auth import require_user
from schemas.shop_schema import StockShopCatalogOut, StockShopPurchaseIn, StockShopPurchaseOut
from services.database import get_db
from services.shop_service import ShopService

router = APIRouter(tags=["shop"])


@router.get("/catalog", response_model=StockShopCatalogOut)
async def list_stock_shop_catalog(
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ShopService.list_catalog(db, user["sub"])


@router.post("/purchase", response_model=StockShopPurchaseOut)
async def purchase_stock_unlock(
    payload: StockShopPurchaseIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_user),
):
    return await ShopService.purchase_unlock(
        db=db,
        user_id=user["sub"],
        symbol=payload.symbol,
        payment_provider=payload.payment_provider,
        provider_transaction_id=payload.provider_transaction_id,
        amount=payload.amount,
        currency=payload.currency,
        payment_status=payload.payment_status,
    )
