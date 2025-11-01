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
    curr_rel = relationship("Currency", back_populates="vend_rel")
    item_rel = relationship("Item", back_populates="vendor_rel")
    top_rel = relationship("TermOfPayment", back_populates="vend_rel")
    
    # These are fine - Vendor owns these, so cascade makes sense
    pembelians = relationship("Pembelian", back_populates="vend_rel")
    pembayarans = relationship("Pembayaran", back_populates="vend_rel")
    pengembalians = relationship("Pengembalian", back_populates="vend_rel")

