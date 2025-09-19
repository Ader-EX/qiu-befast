# models/Penjualan.py
from decimal import Decimal
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, Integer, String, ForeignKey, Numeric, Text, DateTime, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from database import Base
from models.Pembelian import StatusPembayaranEnum, StatusPembelianEnum
from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class Penjualan(Base, SoftDeleteMixin):
    __tablename__ = "penjualans"

    id = Column(Integer, primary_key=True, index=True)
    no_penjualan = Column(String(255), unique=True, default="", nullable=False)

    # Status enums aligned with Pembelian
    status_pembayaran = Column(Enum(StatusPembayaranEnum), default=StatusPembayaranEnum.UNPAID)
    status_penjualan = Column(Enum(StatusPembelianEnum), default=StatusPembelianEnum.DRAFT)

    # Dates aligned with Pembelian
    sales_date = Column(DateTime, nullable=True, default=datetime.now)
    sales_due_date = Column(DateTime, nullable=True, default=lambda: datetime.now() + timedelta(weeks=1))
    currency_amount = Column(Numeric(15,7), default=0.00)


# ---- Totals (match Pembelian header fields) ----
    total_subtotal = Column(Numeric(15, 7), default=0.00)

    total_discount = Column(Numeric(15, 7), default=0.00)
    additional_discount = Column(Numeric(15, 7), default=0.00)

    total_before_discount = Column(Numeric(15, 7), default=0.00)

    total_tax = Column(Numeric(15, 7), default=0.00)
    expense = Column(Numeric(15, 7), default=0.00)
    total_price = Column(Numeric(15, 7), default=0.00)
    total_paid = Column(Numeric(15, 7), default=0.00)
    total_return = Column(Numeric(15, 7), default=0.00)

    # ---- Draft-mode foreign keys (same pattern as Pembelian) ----
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    top_id = Column(Integer, ForeignKey("term_of_payments.id", ondelete="SET NULL"), nullable=True)

    # ---- Finalized snapshot fields (you already had these; kept intact) ----
    warehouse_name = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    customer_address = Column(Text, nullable=True)
    top_name = Column(String(255), nullable=True)
    currency_name = Column(String(255), nullable=True)

    created_at = Column(DateTime, default=datetime.now, nullable=False)

    # ---- Relationships ----
    customer_rel = relationship("Customer", back_populates="penjualans")
    warehouse_rel = relationship("Warehouse", back_populates="penjualans")
    top_rel = relationship("TermOfPayment", back_populates="penjualans")

    penjualan_items = relationship(
        "PenjualanItem",
        back_populates="penjualan",
        cascade="all, delete-orphan",
    )
    pembayaran_detail_rel = relationship(
        "PembayaranDetails",
        back_populates="penjualan_rel",
        cascade="all, delete-orphan",
    )
    pengembalian_detail_rel = relationship(
        "PengembalianDetails",
        back_populates="penjualan_rel",
        cascade="all, delete-orphan",
    )

    attachments = relationship(
        "AllAttachment",
        back_populates="penjualans",
        cascade="all, delete-orphan",
    )

    # ---- Display & computed helpers ----
    @hybrid_property
    def customer_display(self) -> str:
        if self.customer_name:
            return self.customer_name
        if self.customer_rel:
            return self.customer_rel.name
        return "—"

    @hybrid_property
    def customer_address_display(self) -> str:
        if self.customer_address:
            return self.customer_address
        if self.customer_rel:
            return self.customer_rel.address
        return "—"

    @hybrid_property
    def remaining(self) -> Decimal:
        return self.total_price - (self.total_paid + self.total_return)


class PenjualanItem(Base):
    __tablename__ = "penjualan_items"

    id = Column(Integer, primary_key=True, index=True)
    penjualan_id = Column(Integer, ForeignKey("penjualans.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="SET NULL"), nullable=True)

    # ---- Item pricing fields aligned with PembelianItem ----
    qty = Column(Integer, nullable=False, default=0)
    unit_price = Column(Numeric(15, 7), nullable=False, default=0.00)        # harga per unit
    unit_price_rmb = Column(Numeric(15, 7), nullable=False, default=0.00) # harga item per barang in RMB
    tax_percentage = Column(Integer, nullable=True, default=0)               # %
    discount = Column(Numeric(15, 7), default=0.00)                          # nominal discount (not %)
    price_after_tax = Column(Numeric(15, 7), default=0.00)                   # unit price after tax (if you use it)
    sub_total = Column(Numeric(15, 7), default=0.00)                         # qty * (unit_price - discount per unit), before expense
    total_price = Column(Numeric(15, 7), nullable=False, default=0.00)       # final line total

    # ---- Relationships ----
    penjualan = relationship("Penjualan", back_populates="penjualan_items")
    item_rel = relationship("Item", back_populates="penjualan_items")

    # ---- Convenience accessors (kept from your version) ----
    @property
    def primary_image_url(self) -> Optional[str]:
        """
        Return RAW path/filename only; use URL helpers elsewhere.
        """
        if self.item_rel and self.item_rel.attachments:
            for att in self.item_rel.attachments:
                if att.parent_type.name == "ITEMS":
                    return att.file_path
        return None

    @property
    def image_url(self) -> Optional[str]:
        """
        DEPRECATED: Prefer primary_image_url + URL helpers.
        """
        if self.item_rel and self.item_rel.attachments:
            for att in self.item_rel.attachments:
                if att.parent_type.name == "ITEMS":
                    return att.url
        return None

    @property
    def item_code(self) -> Optional[str]:
        return self.item_rel.code if self.item_rel else None
