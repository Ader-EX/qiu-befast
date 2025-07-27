from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

class Vendor(Base):
    __tablename__ = "vendors"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False)
    top_id = Column(Integer, ForeignKey("term_of_payments.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    currency = relationship("Currency", back_populates="vendors")
    top_rel = relationship("TermOfPayment", back_populates="vendors")
    items = relationship("Item", back_populates="vendor_rel")