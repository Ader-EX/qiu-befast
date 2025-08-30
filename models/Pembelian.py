from decimal import Decimal
import enum
from typing import Optional

from pydantic import validator
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime, DECIMAL, Enum
from sqlalchemy.ext.hybrid import hybrid_property

from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta

from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class StatusPembayaranEnum(enum.Enum):
    ALL = "ALL"
    UNPAID = "UNPAID"
    HALF_PAID = "HALF_PAID"
    PAID = "PAID"

class StatusPembelianEnum(enum.Enum):
    ALL = "ALL"
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PROCESSED = "PROCESSED"
    COMPLETED = "COMPLETED"

class Pembelian(Base,SoftDeleteMixin):
    __tablename__ = "pembelians"

    id = Column(Integer, primary_key=True, index=True)
    no_pembelian = Column(String(255),unique=True, default="", nullable=False)
    status_pembayaran = Column(Enum(StatusPembayaranEnum), default=StatusPembayaranEnum.UNPAID)
    status_pembelian = Column(Enum(StatusPembelianEnum), default=StatusPembelianEnum.DRAFT)
  
    additional_discount = Column(Numeric(15,7), default=0.00)
    expense = Column(Numeric(15,7), default=0.00)

    sales_date = Column(DateTime, nullable=True, default=datetime.now)
    sales_due_date = Column(DateTime, nullable=True, default=lambda: datetime.now() + timedelta(weeks=1))

    # Total quantities and prices will be calculated from items
    total_qty = Column(Integer, nullable=False, default=0)
    total_price = Column(Numeric(15,7), default=0.00)
    total_paid = Column(Numeric(15,7), default=0.00)
    total_return = Column(Numeric(15,7), default=0.00)

    # For DRAFT: store foreign keys to allow editing
    # For finalized: store names to preserve data even if master gets deleted
    # Draft mode - foreign keys (nullable when finalized)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    vendor_id = Column(String(50), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True)
    top_id = Column(Integer, ForeignKey("term_of_payments.id", ondelete="SET NULL"), nullable=True)

    # Finalized mode - stored names (nullable when draft)
    warehouse_name = Column(String(255), nullable=True)
    vendor_name = Column(String(255), nullable=True)
    vendor_address = Column(Text, nullable=True)
    top_name = Column(String(255), nullable=True)
    currency_name  = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)  

    # Relationships (only active in draft mode)
    vend_rel = relationship("Vendor", back_populates="pembelians")
    warehouse_rel = relationship("Warehouse", back_populates="pembelians")
    top_rel = relationship("TermOfPayment", back_populates="pembelians")

    # Items relationship
    pembelian_items = relationship("PembelianItem", back_populates="pembelian", cascade="all, delete-orphan")
    pembayaran_detail_rel = relationship("PembayaranDetails", back_populates="pembelian_rel", cascade="all, delete-orphan")
    pengembalian_detail_rel= relationship("PengembalianDetails", back_populates="pembelian_rel", cascade="all, delete-orphan")
    
    attachments = relationship("AllAttachment", back_populates="pembelians", cascade="all, delete-orphan")
    @hybrid_property
    def vendor_display(self) -> str:
        # draft‐mode name always wins; but if it’s empty, try the live FK
        if self.vendor_name:
            return self.vendor_name
        if self.vend_rel:
            return self.vend_rel.name
        return "—"
    
    @hybrid_property
    def remaining(self) -> Decimal:
        return self.total_price - (self.total_paid + self.total_return)


    @hybrid_property
    def vendor_address_display(self) -> str:
        
        if self.vendor_address:
            return self.vendor_address
        if self.vend_rel:
            return self.vend_rel.address
        return "—"
    
   

class PembelianItem(Base):
    __tablename__ = "pembelian_items"

    id = Column(Integer, primary_key=True, index=True)
    pembelian_id = Column(Integer, ForeignKey("pembelians.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="SET NULL"), nullable=True)
    item_name = Column(String(255), nullable=True)
    item_sku = Column(String(100), nullable=True)
    item_type = Column(String(50), nullable=True)
    discount = Column(Numeric(15,7), default=0.00)
    # FINISH_GOOD, RAW_MATERIAL, SERVICE
    satuan_name = Column(String(100), nullable=True)
    tax_percentage = Column(Integer, nullable=True, default=0)
    qty = Column(Integer, nullable=False, default=0)
   
    unit_price = Column(Numeric(15, 7), nullable=False, default=0.00)
    total_price = Column(Numeric(15, 7), nullable=False, default=0.00)  # qty * unit_price

    # Relationships
    pembelian = relationship("Pembelian", back_populates="pembelian_items")
    # attachments = relationship("AllAttachment", back_populates="pembelians", cascade="all, delete-orphan")
    item_rel = relationship("Item", back_populates="pembelian_items")

    @property
    def primary_image_url(self) -> Optional[str]:
        """
        Return the RAW image path/filename for processing by URL helper functions.
        This should return the file path or filename, NOT a full URL.
        """
        if self.item_rel and self.item_rel.attachments:
            for att in self.item_rel.attachments:
                if att.parent_type.name == "ITEMS":
                    # Return the filename or file_path, NOT the full URL
                    return att.file_path  # or att.file_path - whatever contains just the path/filename
        return None

    @property
    def image_url(self) -> Optional[str]:
        """
        DEPRECATED: Use primary_image_url with URL helper functions instead.
        This property is kept for backward compatibility but should not be used
        in new code as it can cause URL duplication issues.
        """
        if self.item_rel and self.item_rel.attachments:
            for att in self.item_rel.attachments:
                if att.parent_type.name == "ITEMS":
                    return att.url
        return None
    
