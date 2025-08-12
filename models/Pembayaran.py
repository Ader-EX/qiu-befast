import enum
from datetime import datetime

from sqlalchemy import Integer, Column, DateTime, Enum, Numeric, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from database import Base
from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class PembayaranPengembalianType(enum.Enum):
    PEMBELIAN = "PEMBELIAN"
    PENJUALAN = "PENJUALAN"

class Pembayaran(Base,SoftDeleteMixin):
    __tablename__ = "pembayarans"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)

    total_qty = Column(Integer, nullable=False, default=0)
    total_price = Column(Numeric(15,7), default=0.00)

    pembelian_id = Column(Integer,ForeignKey("pembelians.id"), nullable=True)
    penjualan_id = Column(Integer,ForeignKey("penjualans.id"), nullable=True)

    reference_type = Column(Enum(PembayaranPengembalianType), nullable=False)

    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=True)
    top_id = Column(Integer, ForeignKey("term_of_payments.id"), nullable=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=True)

    # Finalized mode - stored names (nullable when draft)
    warehouse_name = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    top_name = Column(String(255), nullable=True)
    currency_name  = Column(String(255), nullable=True)

    customer_rel = relationship("Customer", back_populates="pembayarans")
    warehouse_rel = relationship("Warehouse", back_populates="pembayarans")
    top_rel = relationship("TermOfPayment", back_populates="pembayarans")

    pembelian_rel = relationship("Pembelian", back_populates="pembayaran_rel")
    penjualan_rel = relationship("Penjualan", back_populates="pembayaran_rel")
    pembayaran_items = relationship("PembayaranItem", back_populates="pembayaran", cascade="all, delete-orphan")

    attachments = relationship("AllAttachment", back_populates="pembayarans", cascade="all, delete-orphan")
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

class PembayaranItem(Base):
    __tablename__ = "pembayaran_items"

    id = Column(Integer, primary_key=True, index=True)
    pembayaran_id = Column(Integer, ForeignKey("pembayarans.id"), nullable=False)

    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)

    item_name = Column(String(255), nullable=True)
    item_sku = Column(String(100), nullable=True)
    item_type = Column(String(50), nullable=True)  # FINISH_GOOD, RAW_MATERIAL, SERVICE
    satuan_name = Column(String(100), nullable=True)
    vendor_name = Column(String(255), nullable=True)

    qty = Column(Integer, nullable=False, default=0)
    unit_price = Column(Numeric(15, 7), nullable=False, default=0.00)
    total_price = Column(Numeric(15, 7), nullable=False, default=0.00)

    pembayaran = relationship("Pembayaran", back_populates="pembayaran_items")
    item_rel = relationship("Item", back_populates="pembayaran_items")
