from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime, Date
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class Vendor(Base, SoftDeleteMixin):
    __tablename__ = "vendors"
    
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False)
    top_id = Column(Integer, ForeignKey("term_of_payments.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(Date, default=datetime.now(), nullable=False)
    
    # Relationships
    curr_rel = relationship("Currency",cascade="all, delete", back_populates="vend_rel")
    item_rel = relationship("Item",cascade="all, delete", back_populates="vendor_rel")
    top_rel = relationship("TermOfPayment",cascade="all, delete", back_populates="vend_rel")
    pembelians = relationship("Pembelian",cascade="all, delete", back_populates="vend_rel")
    pembayarans = relationship("Pembayaran",cascade="all, delete", back_populates="vend_rel")
    pengembalians = relationship("Pengembalian",cascade="all, delete", back_populates="vend_rel")

