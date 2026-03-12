from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from services.database import Base


class StockShopCatalogItem(Base):
    __tablename__ = "stock_shop_catalog_items"
    __table_args__ = (
        CheckConstraint("unlock_price > 0", name="stock_shop_catalog_unlock_price_check"),
    )

    stock_id = Column(
        BigInteger,
        ForeignKey("vm_stocks.stock_id", ondelete="CASCADE"),
        primary_key=True,
    )
    unlock_price = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(8), nullable=False, server_default="USD")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StockShopPurchase(Base):
    __tablename__ = "stock_shop_purchases"
    __table_args__ = (
        UniqueConstraint(
            "payment_provider",
            "provider_transaction_id",
            name="uq_stock_shop_purchase_provider_txn",
        ),
        CheckConstraint("amount > 0", name="stock_shop_purchases_amount_check"),
        CheckConstraint(
            "payment_status IN ('pending','completed','failed','refunded')",
            name="stock_shop_purchases_status_check",
        ),
    )

    purchase_id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vm_user_wallet.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    stock_id = Column(
        BigInteger,
        ForeignKey("vm_stocks.stock_id", ondelete="RESTRICT"),
        nullable=False,
    )
    payment_provider = Column(String(32), nullable=False)
    provider_transaction_id = Column(String(128), nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(8), nullable=False, server_default="USD")
    payment_status = Column(String(16), nullable=False, server_default="pending")
    metadata_json = Column(JSON, nullable=True)
    purchased_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
