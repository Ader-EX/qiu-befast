# routes/upload.py
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter,Form, UploadFile, File, HTTPException, Depends
import os
import shutil
from uuid import uuid4
import enum

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
from routes.pembelian_routes import calculate_pembelian_totals
from utils import resolve_css_vars
from fastapi.responses import FileResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
import tempfile
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
    - If raw is http(s): return as-is
    - If raw contains 'uploads/items/...': map to /static/items/<filename>
    - If raw is /static/items/... or static/items/...: keep under /static/items/...
    - Otherwise treat as a filename and put under /static/items/<filename>
    Then build an absolute URL using request.url_for or BASE_URL.
    """
    if not raw:
        return ""
    raw = str(raw).strip()

    # Already absolute web URL
    if raw.startswith(("http://", "https://")):
        return raw

    # Extract filename if it's a disk path or 'uploads/items/...'
    filename = None
    if "uploads/items" in raw:
        filename = os.path.basename(raw)
    elif raw.startswith("/"):
        # disk path like /root/backend/uploads/items/uuid.jpg -> take basename
        filename = os.path.basename(raw)
    elif raw.startswith("static/items/"):
        # already a static path; keep the tail
        filename = raw.split("static/items/", 1)[1]
    elif raw.startswith("/static/items/"):
        filename = raw.split("/static/items/", 1)[1]
    else:
        # bare filename or something else -> take basename
        filename = os.path.basename(raw)

    # Build a /static/items/<filename> path
    static_path = f"items/{filename}"

    # Prefer request.url_for to get absolute URL with correct host/proto
    try:
        absolute = str(request.url_for("static", path=static_path))
    except Exception:
        # Fallback to BASE_URL if url_for isn't available
        base = base_url.rstrip("/")
        absolute = f"{base}/static/{static_path}"

    return absolute


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


    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return {
        "attachment_id": attachment.id,
        "file_path": attachment.file_path,
        "url": f"/static/items/{filename}"
    }



@router.get("/{pembelian_id}/invoice/html", response_class=HTMLResponse)
async def view_invoice_html(pembelian_id: int, request: Request, db: Session = Depends(get_db)):
    pembelian = (
        db.query(Pembelian)
        .options(
            joinedload(Pembelian.pembelian_items)
            .joinedload(PembelianItem.item_rel)
            .joinedload(Item.attachments)
        )
        .filter(Pembelian.id == pembelian_id)
        .first()
    )
    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    BASE_URL = os.getenv("BASE_URL", "https://qiu-system.qiuparts.com")

    enhanced_items = []
    for it in pembelian.pembelian_items:
        raw = it.item_rel.primary_image_url if it.item_rel else None
        img_url = to_public_image_url(raw, request, BASE_URL)
        enhanced_items.append({
            "item": it,
            "image_url": img_url,
            "item_name": it.item_name,
            "qty": it.qty,
            "satuan_name": it.satuan_name,
            "tax_percentage": it.tax_percentage,
            "unit_price": it.unit_price,
            "total_price": it.total_price,
        })

    # --- totals (your logic unchanged) ---
    subtotal = Decimal(0)
    tax_amount = Decimal(0)
    for item in pembelian.pembelian_items:
        item_total = Decimal(str(item.total_price or 0))
        subtotal += item_total
        if item.tax_percentage:
            item_tax = item_total * Decimal(str(item.tax_percentage)) / Decimal('100')
            tax_amount += item_tax

    discount = Decimal(str(pembelian.discount or 0))
    additional_discount = Decimal(str(pembelian.additional_discount or 0))
    final_total = subtotal - discount - additional_discount
    expense = Decimal(str(pembelian.expense or 0))
    grand_total = final_total + tax_amount + expense

    totals = {
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "final_total": final_total,
        "grand_total": grand_total,
    }

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "pembelian": pembelian,
            "enhanced_items": enhanced_items,
            "totals": totals,
            "company": {
                "name": "PT. Jayagiri Indo Asia",
                "logo_url": "static/logo.png",
                "address": "Jl. Telkom No.188, Kota Bekasi, Jawa Barat 16340",
                "website": "www.qiupart.com",
                "bank_name": "Bank Mandiri",
                "account_name": "PT. JAYAGIRI INDO ASIA",
                "account_number": "167-00-07971095",
                "representative": "AMAR",
            },
            "css": open("templates/invoice.css").read(),
        },
    )