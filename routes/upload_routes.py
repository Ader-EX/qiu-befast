# routes/upload.py
from datetime import datetime

from fastapi import APIRouter,Form, UploadFile, File, HTTPException, Depends
import os
import shutil
from uuid import uuid4
import enum

from sqlalchemy.orm import Session

from database import get_db
from models.AllAttachment import AllAttachment

router = APIRouter()

class ParentType(enum.Enum):
    PEMBELIANS = "PEMBELIANS"
    PENGEMBALIANS = "PENGEMBALIANS"
    PEMBAYARANS="PEMBAYARANS"
    PENJUALANS="PENJUALANS"
    ITEMS = "ITEMS"


UPLOAD_DIR = os.getenv("UPLOAD_DIR" ,default="uploads/items")
os.makedirs(UPLOAD_DIR, exist_ok=True)  # Ensure dir exists
# routes/upload.py



def save_upload_file(file, upload_dir):
    ext = file.filename.split(".")[-1].lower()
    if ext not in ["jpg", "jpeg", "png", "webp", "pdf"]:
        raise ValueError("Tipe file tidak didukung. Hanya JPG, JPEG, PNG, WEBP, dan PDF yang diperbolehkan.")
    filename = f"{uuid4().hex}.{ext}"
    filepath = os.path.join(upload_dir, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return filename, filepath

@router.post("/upload-image")
def upload_image(
        file: UploadFile = File(...),
        parent_type: ParentType = Form(...),
        parent_id: int = Form(...),
        db: Session = Depends(get_db)
):
    filename, filepath = save_upload_file(file, UPLOAD_DIR)
    attachment = AllAttachment(
        parent_type=parent_type,
        filename=filename,
        file_path=filepath,
        file_size=os.path.getsize(filepath),
        mime_type=file.content_type,
        created_at=datetime.now()
    )
    # Set the correct parent_id field based on parent_type
    if parent_type == ParentType.ITEMS:
        attachment.item_id = parent_id
    elif parent_type == ParentType.PEMBELIANS:
        attachment.pembelian_id = parent_id
    elif parent_type == ParentType.PENJUALANS:
        attachment.penjualan_id = parent_id


    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return {
        "attachment_id": attachment.id,
        "file_path": attachment.file_path,
        "url": f"/static/items/{filename}"
    }