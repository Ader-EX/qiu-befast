
import os
from typing import Optional
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, DateTime, Enum, func
from database import Base
from sqlalchemy.orm import relationship

import enum

from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class ItemTypeEnum(enum.Enum):
    HIGH_QUALITY = "HIGH_QUALITY"
    RAW_MATERIAL = "RAW_MATERIAL"
    SERVICE = "SERVICE"

class Item(Base, SoftDeleteMixin):
    __tablename__ = "items"
    
    id = Column(Integer, primary_key=True, index=True)
    code= Column(String(100), unique=True, nullable=True)
    type = Column(Enum(ItemTypeEnum))
    name = Column(String(100), nullable=False)
    sku = Column(String(100), unique=True,nullable=False, index=True)
    total_item = Column(Integer, default=0, nullable=False)
    min_item = Column(Integer, default=0, nullable=False)
    modal_price = Column(Numeric(24,7), default=0, nullable=False)
    price = Column(Numeric(24,7), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Foreign Key
    category_one = Column(Integer, ForeignKey("categories.id"), nullable=True)
    category_two = Column(Integer, ForeignKey("categories.id"), nullable=True)
    satuan_id = Column(Integer, ForeignKey("satuans.id"), nullable=False)
    vendor_id = Column(String(50), ForeignKey("vendors.id"), nullable=True)


    category_one_rel = relationship("Category", foreign_keys=[category_one])
    category_two_rel = relationship("Category", foreign_keys=[category_two])

    satuan_rel = relationship("Satuan", back_populates="items")
    vendor_rel = relationship("Vendor", back_populates="item_rel")
    attachments = relationship("AllAttachment", back_populates="item_rel", cascade="all, delete-orphan",   primaryjoin="and_(Item.id==foreign(AllAttachment.item_id), AllAttachment.parent_type=='ITEMS')")
    pembelian_items  = relationship("PembelianItem", back_populates="item_rel")
    penjualan_items  = relationship("PenjualanItem", back_populates="item_rel")
    stock_adjustment_items = relationship("StockAdjustmentItem", back_populates="item_rel")

    @property
    def primary_image_url(self) -> Optional[str]:
        if not self.attachments:
            return None

        chosen = self.attachments[0]

        raw_path = getattr(chosen, "file_path", None) or getattr(chosen, "path", None) or getattr(chosen, "filename", None)
        if raw_path is None:
            return None

        # Normalize path
        relative_path = raw_path.replace("\\", "/")
        relative_path = relative_path.lstrip("/")
        relative_path = relative_path.replace("uploads/", "").replace("/root/backend/", "")

        base_url = os.environ.get("BASE_URL", "http://localhost:8000")
        return f"{base_url}/static/{relative_path}"

