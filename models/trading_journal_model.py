import uuid

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from services.database import Base


class VMTradingJournalEntry(Base):
    __tablename__ = "vm_trading_journal_entries"

    entry_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    symbol = Column(String, nullable=False)
    entry_date = Column(Date, nullable=False)
    pnl_amount = Column(Numeric(16, 2), nullable=False, server_default="0")
    note = Column(Text, nullable=False, server_default="")
    linked_order_id = Column(
        BigInteger,
        ForeignKey("vm_user_orders.order_id", ondelete="SET NULL"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
