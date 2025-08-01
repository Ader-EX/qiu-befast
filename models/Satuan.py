from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime


class Satuan(Base):
    __tablename__ = "satuans"
    
    id = Column(Integer, primary_key=True,  index=True)
    name = Column(String(100), nullable=False)
    symbol = Column(String(10), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    
    # Relationships
    items = relationship("Item",cascade="all, delete", back_populates="satuan_rel")