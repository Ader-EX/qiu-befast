# routes/upload.py
from datetime import datetime
from decimal import Decimal
import mimetypes
from urllib.parse import urljoin

from fastapi import APIRouter,Form, UploadFile, File, HTTPException, Depends
import os
import shutil
from uuid import uuid4
import enum

from fastapi.responses import FileResponse
from starlette.requests import Request
from starlette.responses import HTMLResponse

from models.AllAttachment import AllAttachment
from fastapi.templating import Jinja2Templates
from fastapi import APIRouter, Depends
from fastapi import Depends
from sqlalchemy.orm import Session
from database import get_db

from models.Item import Item
from models.Pembelian import Pembelian, PembelianItem
import os
from sqlalchemy.orm import joinedload


router = APIRouter()
templates = Jinja2Templates(directory="templates")

class ParentType(enum.Enum):
    PEMBELIANS = "PEMBELIANS"
    PENGEMBALIANS = "PENGEMBALIANS"
    PEMBAYARANS="PEMBAYARANS"
    PENJUALANS="PENJUALANS"
    ITEMS = "ITEMS"


UPLOAD_DIR = os.getenv("UPLOAD_DIR" ,default="uploads/items")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def to_public_image_url(raw: str, request: Request, base_url: str) -> str:
    """
    Normalize any 'primary_image_url' into an absolute HTTPS URL.
    Fixed version that handles VPS environment path issues.
    
    Args:
        raw: The raw image path from database
        request: FastAPI request object
        base_url: Base URL for the application
    
    Returns:
        Absolute URL for the image
    """
    if not raw:
        return ""
    
    raw = str(raw).strip()

    # Already absolute web URL
    if raw.startswith(("http://", "https://")):
        return raw

    # Clean the raw path to remove unwanted prefixes
    cleaned_path = raw
    
    # Remove problematic prefixes that might be added in different environments
    unwanted_prefixes = [
        "root/backend/",
        "/root/backend/",
        "backend/",
        "/backend/",
    ]
    
    for prefix in unwanted_prefixes:
        if cleaned_path.startswith(prefix):
            cleaned_path = cleaned_path[len(prefix):]
            break
    
    # Extract filename based on different path patterns
    filename = None
    
    if "uploads/items" in cleaned_path:
        filename = os.path.basename(cleaned_path)
    elif cleaned_path.startswith("static/items/"):
        filename = cleaned_path.split("static/items/", 1)[1]
    elif cleaned_path.startswith("/static/items/"):
        filename = cleaned_path.split("/static/items/", 1)[1]
    elif cleaned_path.startswith("items/"):
        filename = cleaned_path.split("items/", 1)[1]
    elif "/" in cleaned_path:
        filename = os.path.basename(cleaned_path)
    else:
        # Just a filename
        filename = cleaned_path

    # Build the static path
    static_path = f"items/{filename}"

    # Try to use FastAPI's url_for first, fallback to manual construction
    try:
        absolute = str(request.url_for("static", path=static_path))
        
        # Fix: Only replace if we're in production and the generated URL doesn't match base_url
        if base_url and base_url != "http://localhost:8000":
            from urllib.parse import urlparse
            parsed_absolute = urlparse(absolute)
            parsed_base = urlparse(base_url)
            
            # Only replace if the domains are different
            if parsed_absolute.netloc != parsed_base.netloc:
                absolute = f"{parsed_base.scheme}://{parsed_base.netloc}{parsed_absolute.path}"
                if parsed_absolute.query:
                    absolute += f"?{parsed_absolute.query}"
                    
    except Exception:
        # Fallback to manual construction
        base = base_url.rstrip("/")
        absolute = f"{base}/static/{static_path}"

    return absolute


def get_public_image_url(image_path: str, base_url: str = None) -> str:
    """
    Alternative cleaner function for generating public image URLs without request dependency.
    
    Args:
        image_path: The raw image path
        base_url: The base URL (uses env var if not provided)
    
    Returns:
        Full public URL for the image
    """
    if not image_path:
        return ""
    
    if not base_url:
        base_url = os.getenv("BASE_URL", "http://localhost:8000")  # Default to localhost for local dev
    
    # Clean the image path - remove any unwanted prefixes
    cleaned_path = str(image_path).strip()
    
    # Remove common unwanted prefixes that might be added in different environments
    unwanted_prefixes = [
        "root/backend/",
        "/root/backend/",
        "backend/",
        "/backend/",
        "static/",
        "/static/"
    ]
    
    for prefix in unwanted_prefixes:
        if cleaned_path.startswith(prefix):
            cleaned_path = cleaned_path[len(prefix):]
            break
    
    # Ensure the path starts with the correct directory structure
    if not cleaned_path.startswith("items/"):
        # If it's just a filename, assume it belongs in the items directory
        if "/" not in cleaned_path:
            cleaned_path = f"items/{cleaned_path}"
        elif "uploads/items" in cleaned_path:
            cleaned_path = f"items/{os.path.basename(cleaned_path)}"
    
    # Build the final URL
    static_path = f"static/{cleaned_path}"
    
    # Use urljoin properly to avoid double slashes
    from urllib.parse import urljoin
    return urljoin(base_url.rstrip('/') + '/', static_path)


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
        parent_type=parent_type.value,
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
    elif parent_type == ParentType.PEMBAYARANS:
        attachment.pembayaran_id= parent_id
    elif parent_type == ParentType.PENGEMBALIANS:
        attachment.pembayaran_id= parent_id


    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return {
        "attachment_id": attachment.id,
        "file_path": attachment.file_path,
        "url": f"/static/items/{filename}"
    }

def _secure_path(base_dir: str, candidate: str) -> str:
    base_dir_abs = os.path.abspath(base_dir)
    cand_abs = os.path.abspath(candidate)
    if os.path.commonpath([cand_abs, base_dir_abs]) != base_dir_abs:
        raise HTTPException(status_code=400, detail="Invalid file path")
    return cand_abs

@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    inline: bool = False,  # set ?inline=true to render in browser if supported
    db: Session = Depends(get_db),
):
    att = db.query(AllAttachment).filter(AllAttachment.id == attachment_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if not att.file_path or not os.path.exists(att.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    safe_path = _secure_path(UPLOAD_DIR, att.file_path)
    media_type = att.mime_type or mimetypes.guess_type(att.filename)[0] or "application/octet-stream"

    # FileResponse sets Content-Disposition: attachment when filename is provided.
    if inline:
        # override to inline
        headers = {"Content-Disposition": f'inline; filename="{att.filename}"'}
        return FileResponse(safe_path, media_type=media_type, headers=headers)

    return FileResponse(safe_path, media_type=media_type, filename=att.filename)

@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: int,
    db: Session = Depends(get_db),
):
    att = db.query(AllAttachment).filter(AllAttachment.id == attachment_id).first()
    if not att:
        # idempotent: deleting a non-existent thing isn't fatal
        raise HTTPException(status_code=404, detail="Attachment not found")

    file_deleted = False
    # Try to remove the file first (safe-path checked)
    if att.file_path:
        try:
            safe_path = _secure_path(UPLOAD_DIR, att.file_path)
            if os.path.exists(safe_path):
                os.remove(safe_path)
                file_deleted = True
        except FileNotFoundError:
            # File already gone; continue with DB delete
            pass
        except Exception as e:
            # If you prefer to block on file errors, raise 500 here instead.
            # For now, we continue and still clean the DB row.
            print(f"Failed to delete file: {e}")

    # Remove the database row
    try:
        db.delete(att)
        db.commit()
    except Exception:
        db.rollback()
        # (Optionally) attempt to restore file if you want strict atomicity.
        raise HTTPException(status_code=500, detail="Failed to delete attachment from database")

    return {
        "deleted": True,
        "attachment_id": attachment_id,
        "file_deleted": file_deleted,
    }