from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Text, DateTime
from database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

from models.mixin.SoftDeleteMixin import SoftDeleteMixin


class Category(Base,SoftDeleteMixin):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    category_type = Column(Integer, nullable=False)  # Only 1 and 2

    # Relationships
    items_category_one = relationship("Item",cascade="all, delete", foreign_keys="Item.category_one", back_populates="category_one_rel")
    items_category_two = relationship("Item",cascade="all, delete", foreign_keys="Item.category_two", back_populates="category_two_rel")

    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)