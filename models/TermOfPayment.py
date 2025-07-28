
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime


class TermOfPayment(Base):
    __tablename__ = "term_of_payments"
    
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    vend_rel = relationship("Vendor", back_populates="top_rel")
    cust_rel = relationship("Customer", back_populates="top_rel")
