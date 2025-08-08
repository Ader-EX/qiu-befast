# routes/upload.py
from datetime import datetime

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
from fastapi.responses import FileResponse
from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa
import tempfile
import os


router = APIRouter()
templates = Jinja2Templates(directory="templates")

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

    from sqlalchemy.orm import joinedload
    pembelian = (
        db.query(Pembelian)
        .options(
            joinedload(Pembelian.pembelian_items)
            .joinedload(PembelianItem.item_rel)
            .joinedload(Item.attachments)  # so image_url resolves without extra queries
        )
        .filter(Pembelian.id == pembelian_id)
        .first()
    )
    if not pembelian:
        raise HTTPException(status_code=404, detail="Pembelian not found")

    totals = calculate_pembelian_totals(db, pembelian_id)

    company = {
        "name": "PT. Jayagiri Indo Asia",
        "logo_url": "static/logo.png",
        "address": "Jl. Telkom No.188, Kota Bekasi, Jawa Barat 16340",
        "website": "www.qiupart.com",
        "bank_name": "Bank Mandiri",
        "account_name": "PT. JAYAGIRI INDO ASIA",
        "account_number": "167-00-07971095",
        "representative": "AMAR",
    }

    with open("templates/invoice.css") as css_file:
        css_content = css_file.read()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "pembelian": pembelian,
            "totals": totals,
            "company": company,
            "css": css_content,
        },
    )
