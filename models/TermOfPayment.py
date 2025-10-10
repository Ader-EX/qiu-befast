
from sqlalchemy import Column, Integer, String, Boolean, Date
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class TermOfPayment(Base,SoftDeleteMixin):
    __tablename__ = "term_of_payments"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(Date, default=datetime.now(), nullable=False)

    # Relationships
    vend_rel = relationship("Vendor", back_populates="top_rel")

    pembelians = relationship("Pembelian", cascade="all, delete", back_populates="top_rel")
    penjualans = relationship("Penjualan", cascade="all, delete", back_populates="top_rel")
