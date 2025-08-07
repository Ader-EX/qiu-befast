from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime, DECIMAL, Enum
from sqlalchemy.orm import relationship

from database import Base
from datetime import datetime, timedelta

from models.Pembelian import StatusPembelianEnum, StatusPembayaranEnum


class Penjualan(Base):
    __tablename__ = "penjualans"

    id = Column(Integer, primary_key=True, index=True )
    created_at = Column(DateTime, default=datetime.now(), nullable=False)
    no_penjualan = Column(String(255),unique=True, default="", nullable=False)

    status_pembayaran = Column(Enum(StatusPembayaranEnum), default=StatusPembayaranEnum.UNPAID)
    status_penjualan = Column(Enum(StatusPembelianEnum), default=StatusPembelianEnum.DRAFT)
    discount = Column(Numeric(15,7), default=0.00)
    additional_discount = Column(Numeric(15,7), default=0.00)
    expense = Column(Numeric(15,7), default=0.00)


    sales_date = Column(DateTime, nullable=True, default=datetime.now)
    sales_due_date = Column(DateTime, nullable=True, default=lambda: datetime.now() + timedelta(weeks=1))

    total_qty = Column(Integer, nullable=False, default=0)
    total_price = Column(Numeric(15,7), default=0.00)
    total_paid = Column(Numeric(15,7), default=0.00)


    # For DRAFT: store foreign keys to allow editing
    # For finalized: store names to preserve data even if master gets deleted

    # Draft mode - foreign keys (nullable when finalized)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=True)

    top_id = Column(Integer, ForeignKey("term_of_payments.id"), nullable=True)

    warehouse_name = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    top_name = Column(String(255), nullable=True)
    currency_name  = Column(String(255), nullable=True)

    customer_rel = relationship("Customer", back_populates="penjualans")
    warehouse_rel = relationship("Warehouse", back_populates="penjualans")
    top_rel = relationship("TermOfPayment", back_populates="penjualans")

    penjualan_items = relationship("PenjualanItem", back_populates="penjualan", cascade="all, delete-orphan")
    pembayaran_rel = relationship("Pembayaran", back_populates="penjualan_rel", cascade="all, delete-orphan")

    attachments = relationship("AllAttachment", back_populates="penjualans", cascade="all, delete-orphan")


class PenjualanItem(Base):
    __tablename__ = "penjualan_items"

    id = Column(Integer, primary_key=True, index=True)
    penjualan_id = Column(Integer, ForeignKey("penjualans.id"), nullable=False)

    # Draft mode - foreign key to item
    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)

    # Finalized mode - stored item data
    item_name = Column(String(255), nullable=True)
    item_sku = Column(String(100), nullable=True)
    item_type = Column(String(50), nullable=True)  # FINISH_GOOD, RAW_MATERIAL, SERVICE
    satuan_name = Column(String(100), nullable=True)
    vendor_name = Column(String(255), nullable=True)

    # Item details for this purchase
    qty = Column(Integer, nullable=False, default=0)
    unit_price = Column(Numeric(15, 7), nullable=False, default=0.00)
    total_price = Column(Numeric(15, 7), nullable=False, default=0.00)  # qty * unit_price

    # Relationships
    penjualan = relationship("Penjualan", back_populates="penjualan_items")
    item_rel = relationship("Item", back_populates="penjualan_items")