import enum

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime, DECIMAL, Enum
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta

class StatusPembayaranEnum(enum.Enum):
    UNPAID = "UNPAID"
    HALF_PAID = "HALF_PAID"
    PAID = "PAID"

class StatusPembelianEnum(enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"

class Pembelian(Base):
    __tablename__ = "pembelians"

    id = Column(Integer, primary_key=True, index=True)
    no_pembelian = Column(String(255),unique=True, default="", nullable=False)
    status_pembayaran = Column(Enum(StatusPembayaranEnum), default=StatusPembayaranEnum.UNPAID)
    status_pembelian = Column(Enum(StatusPembelianEnum), default=StatusPembelianEnum.DRAFT)
    discount = Column(Numeric(15,7), default=0.00)
    additional_discount = Column(Numeric(15,7), default=0.00)
    expense = Column(Numeric(15,7), default=0.00)

    sales_date = Column(DateTime, nullable=True, default=datetime.now)
    sales_due_date = Column(DateTime, nullable=True, default=lambda: datetime.now() + timedelta(weeks=1))

    # Total quantities and prices will be calculated from items
    total_qty = Column(Integer, nullable=False, default=0)
    total_price = Column(Numeric(15,7), default=0.00)

    # For DRAFT: store foreign keys to allow editing
    # For finalized: store names to preserve data even if master gets deleted

    # Draft mode - foreign keys (nullable when finalized)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=True)

    top_id = Column(Integer, ForeignKey("term_of_payments.id"), nullable=True)

    # Finalized mode - stored names (nullable when draft)
    warehouse_name = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    top_name = Column(String(255), nullable=True)
    currency_name  = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)

    # Relationships (only active in draft mode)
    customer_rel = relationship("Customer", back_populates="pembelians")
    warehouse_rel = relationship("Warehouse", back_populates="pembelians")
    top_rel = relationship("TermOfPayment", back_populates="pembelians")

    # Items relationship
    pembelian_items = relationship("PembelianItem", back_populates="pembelian", cascade="all, delete-orphan")
    pembayaran_rel = relationship("Pembayaran", back_populates="pembelian_rel", cascade="all, delete-orphan")


    attachments = relationship("AllAttachment", back_populates="pembelians", cascade="all, delete-orphan")

class PembelianItem(Base):
    __tablename__ = "pembelian_items"

    id = Column(Integer, primary_key=True, index=True)
    pembelian_id = Column(Integer, ForeignKey("pembelians.id"), nullable=False)

    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)

    item_name = Column(String(255), nullable=True)
    item_sku = Column(String(100), nullable=True)
    item_type = Column(String(50), nullable=True)  # FINISH_GOOD, RAW_MATERIAL, SERVICE
    satuan_name = Column(String(100), nullable=True)
    vendor_name = Column(String(255), nullable=True)

    qty = Column(Integer, nullable=False, default=0)
    unit_price = Column(Numeric(15, 7), nullable=False, default=0.00)
    total_price = Column(Numeric(15, 7), nullable=False, default=0.00)  # qty * unit_price



    # Relationships
    pembelian = relationship("Pembelian", back_populates="pembelian_items")
    item_rel = relationship("Item", back_populates="pembelian_items")
