from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class Customer(Base,SoftDeleteMixin):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50),nullable=False, unique=True)
    name = Column(String(50), nullable=False)
    address = Column(String(255) , nullable=False)
    is_active = Column(Boolean, default=True)

    currency_id = Column(Integer, ForeignKey("currencies.id"),nullable=False)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)

   
    curr_rel = relationship("Currency", back_populates="cust_rel")
    kode_lambung_rel = relationship("KodeLambung", back_populates="customer_rel" )
    # pembelians = relationship("Pembelian",cascade="all, delete", back_populates="customer_rel")
    penjualans = relationship("Penjualan",cascade="all, delete", back_populates="customer_rel")
    pembayarans = relationship("Pembayaran",cascade="all, delete", back_populates="customer_rel")
    pengembalians = relationship("Pengembalian",cascade="all, delete", back_populates="customer_rel")


