from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from services.database import Base


class VMStock(Base):
    __tablename__ = "vm_stocks"

    stock_id = Column(BigInteger, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, unique=True)
    name = Column(Text, nullable=False)
    exchange = Column(Text)
    currency = Column(String, nullable=False, server_default="USD")
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VMPriceDaily(Base):
    __tablename__ = "vm_price_daily"
    __table_args__ = (
        UniqueConstraint("stock_id", "price_date", name="vm_price_daily_stock_id_price_date_key"),
    )

    price_id = Column(BigInteger, primary_key=True, autoincrement=True)
    stock_id = Column(
        BigInteger,
        ForeignKey("vm_stocks.stock_id", ondelete="CASCADE"),
        nullable=False,
    )
    price_date = Column(Date, nullable=False)
    open = Column(Numeric(14, 4), nullable=False)
    high = Column(Numeric(14, 4), nullable=False)
    low = Column(Numeric(14, 4), nullable=False)
    close = Column(Numeric(14, 4), nullable=False)
    volume = Column(BigInteger)
    source = Column(String, nullable=False, server_default="twelvedata")
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VMUserWallet(Base):
    __tablename__ = "vm_user_wallet"

    user_id = Column(UUID(as_uuid=True), primary_key=True)
    cash_balance = Column(Numeric(14, 2), nullable=False, server_default="10000.00")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VMUserStockUnlock(Base):
    __tablename__ = "vm_user_stock_unlocks"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vm_user_wallet.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    stock_id = Column(
        BigInteger,
        ForeignKey("vm_stocks.stock_id", ondelete="CASCADE"),
        primary_key=True,
    )
    unlocked_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    unlock_reason = Column(Text)


class VMUserPosition(Base):
    __tablename__ = "vm_user_positions"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="vm_user_positions_quantity_check"),
        CheckConstraint("avg_cost >= 0", name="vm_user_positions_avg_cost_check"),
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vm_user_wallet.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    stock_id = Column(
        BigInteger,
        ForeignKey("vm_stocks.stock_id", ondelete="CASCADE"),
        primary_key=True,
    )
    quantity = Column(Numeric(20, 6), nullable=False, server_default="0")
    avg_cost = Column(Numeric(14, 4), nullable=False, server_default="0")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class VMUserOrder(Base):
    __tablename__ = "vm_user_orders"
    __table_args__ = (
        CheckConstraint("side IN ('buy','sell')", name="vm_user_orders_side_check"),
        CheckConstraint("quantity > 0", name="vm_user_orders_quantity_check"),
        CheckConstraint("unit_price > 0", name="vm_user_orders_unit_price_check"),
        CheckConstraint("gross_amount > 0", name="vm_user_orders_gross_amount_check"),
        CheckConstraint("fee_amount >= 0", name="vm_user_orders_fee_amount_check"),
        CheckConstraint("net_amount > 0", name="vm_user_orders_net_amount_check"),
    )

    order_id = Column(BigInteger, primary_key=True, autoincrement=True)
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
    side = Column(String, nullable=False)
    quantity = Column(Numeric(20, 6), nullable=False)
    unit_price = Column(Numeric(14, 4), nullable=False)
    gross_amount = Column(Numeric(16, 4), nullable=False)
    fee_amount = Column(Numeric(16, 4), nullable=False, server_default="0")
    net_amount = Column(Numeric(16, 4), nullable=False)
    realized_pnl = Column(Numeric(16, 4))
    price_date = Column(Date, nullable=False)
    client_order_id = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
