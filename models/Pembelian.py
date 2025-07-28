from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime, DECIMAL
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta

class Pembelian(Base):
    __tablename__ = "pembelians"
    
    id = Column(String(50), primary_key=True, index=True)
    sales_date = Column(DateTime, nullable=True, default=datetime.now)
    sales_due_date = Column(DateTime, nullable=True, default=lambda: datetime.now() + timedelta(weeks=1)) 
    qty_pembelian = Column(Integer, nullable=False, default=0)
    price_pembelian  = Column(Numeric(15,2), default=0.00)
    no_pembelian = Column(String(255), default="", nullable=True)

    vendor_id = Column(Integer,ForeignKey("vendors.id"),nullable=False )
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)

    # SALAH, KARENA HARUSNYA INI ITEM_IDS
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)

    vendor_rel = relationship("Vendor", back_populates="pembelians")
    warehouse_rel = relationship("Warehouse", back_populates="pembelians")
    item_rel = relationship("Item", back_populates="pembelians")

    attachments = relationship("AllAttachment", back_populates="pembelians", cascade="all, delete-orphan")

