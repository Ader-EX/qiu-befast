from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

class Vendor(Base):
    __tablename__ = "vendors"
    
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    currency_id = Column(Integer, ForeignKey("currencies.id"), nullable=False)
    top_id = Column(Integer, ForeignKey("term_of_payments.id"), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    
    # Relationships
    curr_rel = relationship("Currency",cascade="all, delete", back_populates="vend_rel")
    top_rel = relationship("TermOfPayment",cascade="all, delete", back_populates="vend_rel")
    pembelians = relationship("Pembelian",cascade="all, delete", back_populates="vendor_rel")

    items = relationship("Item", back_populates="vendor_rel")