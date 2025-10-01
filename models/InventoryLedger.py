
from __future__ import annotations


from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Literal
import enum

from sqlalchemy import (
    Column, Integer, BigInteger, Numeric, String, DateTime, Date, Boolean,
    Enum as SAEnum, Index, UniqueConstraint, func, case, and_, or_, asc, desc
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
    source_id = Column(String(64), nullable=False) # e.g., "PEMBELIAN_ITEM:12345"


    # Movement quantities (non-negative)
    qty_in = Column(Integer, nullable=False, default=0)
    qty_out = Column(Integer, nullable=False, default=0)


    # For IN rows; OUT rows keep unit_price as previous moving average (optional)
    unit_price = Column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    value_in = Column(Numeric(18, 6), nullable=False, default=Decimal("0")) # qty_in * unit_price


    # Cumulative state AFTER applying this row
    cumulative_qty = Column(Integer, nullable=False)
    moving_avg_cost = Column(Numeric(18, 6), nullable=False)
    cumulative_value = Column(Numeric(18, 6), nullable=False)


    # Audit / integrity
    order_key = Column(String(64), nullable=False) # strict ordering inside equal timestamps
    reason_code = Column(String(64), nullable=True)
    voided = Column(Boolean, nullable=False, default=False)
    reversal_of_ledger_id = Column(BigInteger, nullable=True)


    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=func.now())


    __table_args__ = (
        # Prevent duplicate posting for the same source line
        UniqueConstraint(
            "item_id",  "source_type", "source_id",
            name="uq_ledger_uniqueness"
        ),
        Index("ix_ledger_item_wh_date", "item_id",  "trx_date", "id"),
)