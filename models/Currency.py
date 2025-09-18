from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

from models.Customer import Customer
from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class Currency(Base,SoftDeleteMixin):
    __tablename__ = "currencies"
    
    id = Column(Integer, primary_key=True,  index=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)

    
    # Relationships
    vend_rel = relationship("Vendor", cascade="all, delete", back_populates="curr_rel")
    cust_rel = relationship("Customer", cascade="all, delete", back_populates="curr_rel")
    
    pembayarans = relationship("Pembayaran", cascade="all, delete", back_populates="curr_rel")
    pengembalians = relationship("Pengembalian", cascade="all, delete", back_populates="curr_rel")