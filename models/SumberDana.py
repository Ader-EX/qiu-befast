from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship

from database import Base
from models.mixin import SoftDeleteMixin


class SumberDana(Base, SoftDeleteMixin):
    __tablename__ = "sumberdanas"
    id = Column(Integer, primary_key=True,  index=True)
    name = Column(String(100), nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now(), nullable=False)

    pembelians= relationship("Pembelian", cascade="all,delete", back_populates="sumberdana_rel")

