
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime,Enum
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
class ItemTypeEnum(enum.Enum):
    FINISH_GOOD = "FINISH GOOD"
    RAW_MATERIAL = "RAW_MATERIAL"
    SERVICE = "SERVICE"

class Item(Base):
    __tablename__ = "items"
    
    id = Column(Integer, primary_key=True, index=True)
    type = Column(Enum(ItemTypeEnum))
    name = Column(String(100), nullable=False)
    sku = Column(String(100), unique=True, nullable=False, index=True)
    total_item = Column(Integer, default=0, nullable=False)
    price = Column(Numeric(15, 2), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Foreign Keys
    category_one = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_two = Column(Integer, ForeignKey("categories.id"), nullable=True)
    satuan_id = Column(Integer, ForeignKey("satuans.id"), nullable=False)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    category_one_rel = relationship("Category", foreign_keys=[category_one])
    category_two_rel = relationship("Category", foreign_keys=[category_two])
    satuan_rel = relationship("Satuan", back_populates="items")
    vendor_rel = relationship("Vendor", back_populates="items")
    attachments = relationship("ItemAttachment", back_populates="item", cascade="all, delete-orphan")