from datetime import datetime

from sqlalchemy import Integer, Column, DateTime, Enum, Numeric, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from database import Base
from models.Pembelian import StatusPembelianEnum
from schemas.PembayaranSchemas import PembayaranPengembalianType


class Pengembalian(Base):
    __tablename__ = "pengembalians"

    id = Column(Integer, primary_key=True, index=True)
    no_pengembalian = Column(String(255), unique=True, default="", nullable=False)
    status = Column(Enum(StatusPembelianEnum), default=StatusPembelianEnum.DRAFT)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)
    
    payment_date = Column(DateTime, nullable=False)

    reference_type = Column(Enum(PembayaranPengembalianType), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    vendor_id = Column(String(50), ForeignKey("vendors.id"), nullable=True)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)

    # Relationships
    customer_rel = relationship("Customer", back_populates="pengembalians")
    vend_rel = relationship("Vendor", back_populates="pengembalians")
    warehouse_rel = relationship("Warehouse", back_populates="pengembalians")
    curr_rel = relationship("Currency", back_populates="pengembalians")
    
    pengembalian_details = relationship("PengembalianDetails", back_populates="pengembalian_rel", cascade="all, delete-orphan")
    
    attachments = relationship("AllAttachment", back_populates="pengembalians", cascade="all, delete-orphan")



class PengembalianDetails(Base):
    __tablename__ = "pengembalian_details"

    id = Column(Integer, primary_key=True, index=True)
    pengembalian_id = Column(Integer, ForeignKey("pengembalians.id"), nullable=False)
    pembelian_id = Column(Integer, ForeignKey("pembelians.id"), nullable=True)
    penjualan_id = Column(Integer, ForeignKey("penjualans.id"), nullable=True)

    total_return = Column(Numeric(15,7), default=0.00)

    pengembalian_rel = relationship("Pengembalian", back_populates="pengembalian_details")
    pembelian_rel = relationship("Pembelian", back_populates="pengembalian_detail_rel")
    penjualan_rel = relationship("Penjualan", back_populates="pengembalian_detail_rel")

