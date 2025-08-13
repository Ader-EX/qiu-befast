from decimal import Decimal
import enum
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, ForeignKey, Numeric, Text, DateTime, Enum, Boolean
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from database import Base
from datetime import datetime, timedelta

from models.Pembelian import StatusPembayaranEnum, StatusPembelianEnum
from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class Penjualan(Base,SoftDeleteMixin):
    __tablename__ = "penjualans"

    id = Column(Integer, primary_key=True, index=True)
    no_penjualan = Column(String(255), unique=True, default="", nullable=False)
    status_pembayaran = Column(Enum(StatusPembayaranEnum), default=StatusPembayaranEnum.UNPAID)
    status_penjualan = Column(Enum(StatusPembelianEnum), default=StatusPembelianEnum.DRAFT)
    discount = Column(Numeric(15, 7), default=0.00)
    additional_discount = Column(Numeric(15, 7), default=0.00)
    expense = Column(Numeric(15, 7), default=0.00)

    sales_date = Column(DateTime, nullable=True, default=datetime.now)
    sales_due_date = Column(DateTime, nullable=True, default=lambda: datetime.now() + timedelta(weeks=1))

    # Total quantities and prices will be calculated from items
    total_qty = Column(Integer, nullable=False, default=0)
    total_price = Column(Numeric(15, 7), default=0.00)
    total_paid = Column(Numeric(15, 7), default=0.00)
    total_return = Column(Numeric(15, 7), default=0.00) # Added for consistency with Pembelian

    # For DRAFT: store foreign keys to allow editing
    # For finalized: store names to preserve data even if master gets deleted
    # Draft mode - foreign keys (nullable when finalized)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(String(50), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    top_id = Column(Integer, ForeignKey("term_of_payments.id", ondelete="SET NULL"), nullable=True)

    # Finalized mode - stored names (nullable when draft)
    warehouse_name = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    customer_address = Column(Text, nullable=True) # Added for consistency
    top_name = Column(String(255), nullable=True)
    currency_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # Relationships (only active in draft mode)
    customer_rel = relationship("Customer", back_populates="penjualans")
    warehouse_rel = relationship("Warehouse", back_populates="penjualans")
    top_rel = relationship("TermOfPayment", back_populates="penjualans")

    # Items relationship
    penjualan_items = relationship("PenjualanItem", back_populates="penjualan", cascade="all, delete-orphan")
    pembayaran_detail_rel = relationship("PembayaranDetails", back_populates="penjualan_rel", cascade="all, delete-orphan")
    attachments = relationship("AllAttachment", back_populates="penjualans", cascade="all, delete-orphan")
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    @hybrid_property
    def customer_display(self) -> str:
        """
        Provides a display name for the customer.
        Prioritizes the stored name, but falls back to the related object's name.
        """
        if self.customer_name:
            return self.customer_name
        if self.customer_rel:
            return self.customer_rel.name
        return "—"

    @hybrid_property
    def remaining(self) -> Decimal:
        """Calculates the outstanding balance."""
        return self.total_price - (self.total_paid + self.total_return)

    @hybrid_property
    def customer_address_display(self) -> str:
        """
        Provides a display address for the customer.
        Prioritizes the stored address, but falls back to the related object's address.
        """
        if self.customer_address:
            return self.customer_address
        if self.customer_rel:
            return self.customer_rel.address
        return "—"


class PenjualanItem(Base):
    __tablename__ = "penjualan_items"

    id = Column(Integer, primary_key=True, index=True)
    penjualan_id = Column(Integer, ForeignKey("penjualans.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="SET NULL"), nullable=True)

    # Finalized mode - stored item data
    item_name = Column(String(255), nullable=True)
    item_sku = Column(String(100), nullable=True)
    item_type = Column(String(50), nullable=True)  # e.g., FINISH_GOOD, RAW_MATERIAL, SERVICE
    satuan_name = Column(String(100), nullable=True)
    tax_percentage = Column(Integer, nullable=True, default=0) # Added for consistency

    # Item details for this sale
    qty = Column(Integer, nullable=False, default=0)
    unit_price = Column(Numeric(15, 7), nullable=False, default=0.00)
    total_price = Column(Numeric(15, 7), nullable=False, default=0.00)  # qty * unit_price

    # Relationships
    penjualan = relationship("Penjualan", back_populates="penjualan_items")
    item_rel = relationship("Item", back_populates="penjualan_items")

    @property
    def image_url(self) -> Optional[str]:
        """
        Prefer the first attachment uploaded for this Item (ParentType.ITEMS).
        Falls back to None if no item image exists.
        """
        if self.item_rel and self.item_rel.attachments:
            # Assumes an attachment model with 'parent_type' and 'url' attributes
            for att in self.item_rel.attachments:
                if att.parent_type.name == "ITEMS":
                    return att.url
        return None
