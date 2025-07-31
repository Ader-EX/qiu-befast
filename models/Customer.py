from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime, DECIMAL
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta



class Customer(Base):
    __tablename__ = "customers"
    id = Column(String(50), primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    address = Column(String(255) , nullable=False)
    is_active = Column(Boolean, default=True)

    top_id = Column(Integer, ForeignKey("term_of_payments.id"), nullable=False)
    currency_id = Column(Integer, ForeignKey("currencies.id"),nullable=False)

    top_rel = relationship("TermOfPayment",back_populates="cust_rel")
    curr_rel = relationship("Currency", back_populates="cust_rel")

