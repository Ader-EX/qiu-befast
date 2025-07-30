from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime, Enum
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

class ParentType(enum.Enum):
    PEMBELIANS = "PEMBELIANS"
    PENGEMBALIANS = "PENGEMBALIANS"
    PEMBAYARANS="PEMBAYARANS"
    PENJUALANS="PENJUALANS"
    ITEMS = "ITEMS"

class AllAttachment(Base):
    __tablename__ = "all_attachments"
    
    id = Column(Integer, primary_key=True, index=True)

    parent_type = Column(Enum(ParentType), nullable=False)
    parent_id =      Column(String(50), nullable=False)


    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)
    pembelian_id = Column(String(50), ForeignKey("pembelians.id"), nullable=True)
    # penjualan_id = Column(Integer, ForeignKey("penjualans.id"), nullable=True)
    # pembayaran_id = Column(Integer, ForeignKey("pembayarans.id"), nullable=True)
    # pengembalian_id = Column(Integer, ForeignKey("pengembalians.id"), nullable=True)

    item_rel = relationship("Item", back_populates="attachments")
    pembelians = relationship("Pembelian", back_populates="attachments")

    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    
