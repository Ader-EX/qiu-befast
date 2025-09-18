from datetime import datetime

from pydantic import BaseModel, validator
from typing import Optional


class CategoryBase(BaseModel):
    name: str
    is_active: Optional[bool] = True
    category_type: int = 1
    created_at: datetime

    @validator("category_type")
    def validate_category_type(cls, v):
        if v not in [1, 2]:
            raise ValueError("category_type must be 1 or 2")
        return v


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(CategoryBase):
    pass


class CategoryOut(CategoryBase):
    id: int

    class Config:
        from_attributes = True
