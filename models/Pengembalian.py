from datetime import datetime
from typing import Optional
from decimal import Decimal

from sqlalchemy import Integer, Column, DateTime, Enum, Numeric, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from database import Base
from models.Pembelian import StatusPembelianEnum
from schemas.PembayaranSchemas import PembayaranPengembalianType


class Pengembalian(Base):
    __tablename__ = "pengembalians"

    id = Column(Integer, primary_key=True, index=True)
    no_pengembalian = Column(String(255), unique=True, default="", nullable=False)
    status = Column(Enum(StatusPembelianEnum), default=StatusPembelianEnum.DRAFT)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    
    payment_date = Column(DateTime, nullable=False)

    # Single reference - either pembelian OR penjualan
    reference_type = Column(Enum(PembayaranPengembalianType), nullable=False)
    pembelian_id = Column(Integer, ForeignKey("pembelians.id", ondelete="SET NULL"), nullable=True)
    penjualan_id = Column(Integer, ForeignKey("penjualans.id", ondelete="SET NULL"), nullable=True)

    # Partner info
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    vendor_id = Column(String(50), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True)
    
    # Other info
    currency_id = Column(Integer, ForeignKey("currencies.id", ondelete="SET NULL"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=False)

    # Totals (simpler than Pembelian - NO discounts)
    total_subtotal = Column(Numeric(24, 7), default=0.00)  # Sum of all item sub_totals (qty * price)
    total_tax = Column(Numeric(24, 7), default=0.00)  # Sum of all item taxes
    total_return = Column(Numeric(24, 7), default=0.00)  # Final total (subtotal + tax)
    
    notes = Column(String(500), nullable=True)

    # Relationships
    customer_rel = relationship("Customer", back_populates="pengembalians")
    vend_rel = relationship("Vendor", back_populates="pengembalians")
    warehouse_rel = relationship("Warehouse", back_populates="pengembalians")
    curr_rel = relationship("Currency", back_populates="pengembalians")
    pembelian_rel = relationship("Pembelian", back_populates="pengembalian_rel")
    penjualan_rel = relationship("Penjualan", back_populates="pengembalian_rel")
    
    # Items relationship
    pengembalian_items = relationship("PengembalianItem", back_populates="pengembalian_rel", cascade="all, delete-orphan")
    
    attachments = relationship("AllAttachment", back_populates="pengembalians", cascade="all, delete-orphan")

    @hybrid_property
    def reference_number(self) -> str:
        """Get the reference document number"""
        if self.reference_type == PembayaranPengembalianType.PEMBELIAN and self.pembelian_rel:
            return self.pembelian_rel.no_pembelian
        elif self.reference_type == PembayaranPengembalianType.PENJUALAN and self.penjualan_rel:
            return self.penjualan_rel.no_penjualan
        return "—"

    @hybrid_property
    def partner_display(self) -> str:
        """Get the partner name (vendor or customer)"""
        if self.reference_type == PembayaranPengembalianType.PEMBELIAN:
            if self.vend_rel:
                return self.vend_rel.name
        elif self.reference_type == PembayaranPengembalianType.PENJUALAN:
            if self.customer_rel:
                return self.customer_rel.name
        return "—"


class PengembalianItem(Base):
    """Item details for return - simpler than PembelianItem (NO discount)"""
    __tablename__ = "pengembalian_items"

    id = Column(Integer, primary_key=True, index=True)
    pengembalian_id = Column(Integer, ForeignKey("pengembalians.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    
    # Item snapshot data (in case item is deleted later)
    item_code = Column(String(255), nullable=True)
    item_name = Column(String(500), nullable=True)
    
    # Return quantities and amounts (NO discount field)
    qty_returned = Column(Integer, nullable=False, default=0)
    unit_price = Column(Numeric(24, 7), nullable=False, default=0.00)
    tax_percentage = Column(Integer, nullable=True, default=0)
    
    # Computed totals
    sub_total = Column(Numeric(24, 7), default=0.00)  # qty_returned * unit_price
    total_return = Column(Numeric(24, 7), nullable=False, default=0.00)  # sub_total + tax

    # Relationships
    pengembalian_rel = relationship("Pengembalian", back_populates="pengembalian_items")
    item_rel = relationship("Item", back_populates="pengembalian_items")

    @property
    def primary_image_url(self) -> Optional[str]:
        """Return the RAW image path/filename for processing by URL helper functions"""
        if self.item_rel and self.item_rel.attachments:
            for att in self.item_rel.attachments:
                if att.parent_type.name == "ITEMS":
                    return att.file_path
        return None

    @property
    def item_display_code(self) -> str:
        """Return item code - prioritize snapshot, fallback to relationship"""
        if self.item_code:
            return self.item_code
        if self.item_rel:
            return self.item_rel.code
        return "—"

    @property
    def item_display_name(self) -> str:
        """Return item name - prioritize snapshot, fallback to relationship"""
        if self.item_name:
            return self.item_name
        if self.item_rel:
            return self.item_rel.name
        return "—"