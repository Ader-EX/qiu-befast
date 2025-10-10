import enum
from datetime import datetime

from sqlalchemy import Column, Integer, String, Enum, Date, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from database import Base
from models import SoftDeleteMixin


class AdjustmentTypeEnum(enum.Enum):
    IN = "IN"
    OUT = "OUT"


class StatusStockAdjustmentEnum(enum.Enum):
    ALL = "ALL"
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"

class StockAdjustment(Base, SoftDeleteMixin):
    __tablename__ = "stock_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    no_adjustment = Column(String(255),unique=True, default="", nullable=False)
    adjustment_type= Column(Enum(AdjustmentTypeEnum), nullable=False)
    status_adjustment = Column(Enum(StatusStockAdjustmentEnum), default=StatusStockAdjustmentEnum.DRAFT, nullable=False)

    adjustment_date = Column(Date, nullable=False)

    warehouse_id = Column(Integer, ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True)
    warehouse_rel = relationship("Warehouse", back_populates="stock_adjustments")

    attachments = relationship("AllAttachment", back_populates="stock_adjustments", cascade="all, delete-orphan")
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    stock_adjustment_items = relationship("StockAdjustmentItem", back_populates="stock_adjustment_rel", cascade="all, delete-orphan")


class StockAdjustmentItem(Base):
    __tablename__ = "stock_adjustment_items"

    id = Column(Integer, primary_key=True, index=True)
    stock_adjustment_id = Column(Integer, ForeignKey("stock_adjustments.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id", ondelete="SET NULL"), nullable=True)

    qty = Column(Integer, nullable=False, default=0)
    adj_price = Column(Integer, nullable=False, default=0)

    stock_adjustment_rel = relationship("StockAdjustment", back_populates="stock_adjustment_items")
    item_rel = relationship("Item", back_populates="stock_adjustment_items")





