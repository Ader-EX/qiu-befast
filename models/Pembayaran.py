import enum
from datetime import datetime

from sqlalchemy import Integer, Column, DateTime, Enum, Numeric, ForeignKey, String, Boolean
from sqlalchemy.orm import relationship
from database import Base
from models.mixin.SoftDeleteMixin import SoftDeleteMixin
from schemas.PembayaranSchemas import PembayaranPengembalianType


class Pembayaran(Base, SoftDeleteMixin):
    __tablename__ = "pembayarans"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)
    
    payment_date = Column(DateTime, nullable=False)
    total_paid = Column(Numeric(15,7), default=0.00)

    reference_type = Column(Enum(PembayaranPengembalianType), nullable=False)
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=True)
    vendor_id = Column(String(50), ForeignKey("vendors.id"), nullable=True)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)

    warehouse_name = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    currency_name = Column(String(255), nullable=True)

    # Relationships
    customer_rel = relationship("Customer", back_populates="pembayarans")
    warehouse_rel = relationship("Warehouse", back_populates="pembayarans")
    curr_rel = relationship("Currency", back_populates="pembayarans")
    
    pembayaran_details = relationship("PembayaranDetails", back_populates="pembayaran_rel", cascade="all, delete-orphan")
    
    attachments = relationship("AllAttachment", back_populates="pembayarans", cascade="all, delete-orphan")



class PembayaranDetails(Base, SoftDeleteMixin):
    __tablename__ = "pembayaran_details"

    id = Column(Integer, primary_key=True, index=True)
    pembayaran_id = Column(Integer, ForeignKey("pembayarans.id"), nullable=False)
    pembelian_id = Column(Integer, ForeignKey("pembelians.id"), nullable=True)
    penjualan_id = Column(Integer, ForeignKey("penjualans.id"), nullable=True)

    total_paid = Column(Numeric(15, 7), default=0.00)

    pembayaran_rel = relationship("Pembayaran", back_populates="pembayaran_details")
    pembelian_rel = relationship("Pembelian", back_populates="pembayaran_detail_rel")
    penjualan_rel = relationship("Penjualan", back_populates="pembayaran_detail_rel")

