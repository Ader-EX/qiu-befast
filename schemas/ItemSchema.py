import os
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, computed_field

from models.Item import ItemTypeEnum
from schemas.CategorySchemas import CategoryOut
from schemas.SatuanSchemas import SatuanOut
from schemas.TopSchemas import TopOut
from schemas.VendorSchemas import VendorOut


class AttachmentResponse(BaseModel):
    id: int
    filename: str
    file_path: str
    file_size: Optional[int]
    mime_type: Optional[str]
    created_at: datetime
    # url:str

    class Config:
        from_attributes = True

    def to_url(self):
        return f"/static/{self.file_path}"
    
    @computed_field
    @property
    def url(self) -> str:
        base_url = os.environ.get("BASE_URL", "http://localhost:8000/static")
        clean_path = self.file_path.replace("\\", "/").replace("uploads/", "")
        return f"{base_url}/static/{clean_path}"





class ItemBase(BaseModel):
    type: ItemTypeEnum
    name: str
    sku: str
    total_item: int = 0
    price: float


    category_one_rel: Optional[CategoryOut] = None
    category_two_rel: Optional[CategoryOut] = None

    satuan_rel: Optional[SatuanOut] = None
    vendor_rel: Optional[VendorOut] = None
    class Config:
        from_attributes = True


class ItemCreate(ItemBase):
    category_one_id: Optional[int] = None
    category_two_id: Optional[int] = None
    satuan_id: Optional[int] = None
    vendor_id: Optional[int] = None

    category_one_rel: Optional[TopOut] = None
    category_two_rel: Optional[TopOut] = None


class ItemUpdate(ItemBase):
    category_one_id: Optional[int] = None
    category_two_id: Optional[int] = None
    satuan_id: Optional[int] = None
    vendor_id: Optional[int] = None

    category_one_rel: Optional[TopOut] = None
    category_two_rel: Optional[TopOut] = None
    class Config:
        from_attributes = True


class ItemResponse(ItemBase):
    id: int
    created_at: Optional[datetime] = None
    attachments: List[AttachmentResponse] = []

    class Config:
        from_attributes = True