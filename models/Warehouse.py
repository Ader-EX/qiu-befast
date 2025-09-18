from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime
from database import Base
from sqlalchemy.orm import relationship
from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class Warehouse(Base,SoftDeleteMixin):
    __tablename__ = "warehouses"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)

    pembelians  = relationship("Pembelian",cascade="all, delete", back_populates="warehouse_rel")
    penjualans  = relationship("Penjualan",cascade="all, delete", back_populates="warehouse_rel")
    pembayarans  = relationship("Pembayaran",cascade="all, delete", back_populates="warehouse_rel")
    pengembalians  = relationship("Pengembalian",cascade="all, delete", back_populates="warehouse_rel")

