from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime, DECIMAL
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta

class Penjualan(Base):
    __tablename__ = "penjualans"

    id = Column(String(50), primary_key=True, index=True )
    created_at = Column(DateTime, default=datetime.now(), nullable=False)
    