from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta

class Pembelian(Base):
    __tablename__ = "pembelian"
    
    id = Column(String(50), primary_key=True, index=True)
    sales_date = Column(DateTime, nullable=True, default=datetime.now)
    sales_due_date = Column(DateTime, nullable=True, default=lambda: datetime.now() + timedelta(weeks=1)) 
    qty_pembelian = Column(Integer, nullable=False, default=0)
    price_pembelian  = Column(Integer, default=0)
    
    
