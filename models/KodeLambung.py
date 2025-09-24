from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, ForeignKey
from database import Base
from models.mixin.SoftDeleteMixin import SoftDeleteMixin

from sqlalchemy.orm import relationship


class KodeLambung(Base,SoftDeleteMixin):
    __tablename__ = "kode_lambungs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    customer_rel = relationship("Customer", cascade="all, delete", back_populates="kode_lambung_rel")
    penjualans = relationship("Penjualan", back_populates="kode_lambung_rel")

    def __str__(self):
        return self.name