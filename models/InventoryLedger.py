from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import enum

from sqlalchemy import (
    Column, Integer, BigInteger, Numeric, String, DateTime, Date, Boolean,
    Enum as SAEnum, Index,  func
)

from database import Base

class SourceTypeEnum(str, enum.Enum):
    PEMBELIAN = "PEMBELIAN"
    PENJUALAN = "PENJUALAN"
    IN = "IN"
    OUT = "OUT"
    ITEM = "ITEM"

class InventoryLedger(Base):
    __tablename__ = "inventory_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)

    item_id = Column(Integer, nullable=False, index=True)
    trx_date = Column(Date, nullable=False, index=True)
    source_type = Column(SAEnum(SourceTypeEnum), nullable=False, index=True)
    source_id = Column(String(64), nullable=False)

    qty_in = Column(Integer, nullable=False, default=0)
    qty_out = Column(Integer, nullable=False, default=0)

    unit_price = Column(Numeric(20, 7), nullable=False, default=Decimal("0"))
    value_in = Column(Numeric(20, 7), nullable=False, default=Decimal("0"))

    cumulative_qty = Column(Integer, nullable=False)
    moving_avg_cost = Column(Numeric(20, 7), nullable=False)
    cumulative_value = Column(Numeric(20, 7), nullable=False)

    order_key = Column(String(64), nullable=False)
    reason_code = Column(String(64), nullable=True)
    voided = Column(Boolean, nullable=False, default=False)
    reversal_of_ledger_id = Column(BigInteger, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())

    __table_args__ = (
        # REMOVED: UniqueConstraint("item_id", "source_type", "source_id", ...)
        Index("ix_ledger_item_wh_date", "item_id", "trx_date", "id"),
    )