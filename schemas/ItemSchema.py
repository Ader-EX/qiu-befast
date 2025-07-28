from fastapi import FastAPI, Depends, HTTPException, File, UploadFile, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import get_db, engine
from typing import List, Optional
import shutil
import os
import uuid
import enum

from datetime import datetime
from pydantic import BaseModel
from models import Item, AllAttachment

from models.Item import ItemTypeEnum

class ItemBase(BaseModel):
    type: ItemTypeEnum
    name: str
    sku: str
    total_item: int = 0
    price: float
    is_active: bool = True
    category_one: Optional[int] = None
    category_two: Optional[int] = None
    satuan_id: int
    vendor_id: int

class ItemCreate(ItemBase):
    pass

class ItemUpdate(ItemBase):
    pass

class ItemResponse(ItemBase):
    id: int
    created_at: Optional[datetime] = None
    attachments: List[dict] = []

    class Config:
        from_attributes = True

class AttachmentResponse(BaseModel):
    id: int
    filename: str
    file_path: str
    file_size: Optional[int]
    mime_type: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True