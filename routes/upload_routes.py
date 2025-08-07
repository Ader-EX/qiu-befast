# routes/upload.py
from datetime import datetime

from fastapi import APIRouter,Form, UploadFile, File, HTTPException, Depends
import os
import shutil
from uuid import uuid4
import enum

from sqlalchemy.orm import Session, joinedload
from starlette.requests import Request
from starlette.responses import HTMLResponse

from database import get_db
from models.AllAttachment import AllAttachment
from models.Pembelian import Pembelian

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


@router.get("/invoice/{invoice_id}", response_class=HTMLResponse)
def invoice_report(
        request: Request,
        invoice_id: int,
        db: Session = Depends(get_db),
):
    invoice = (
        db.query(Pembelian)
        .options(
            joinedload(Pembelian.pembelian_items),
            joinedload(Pembelian.customer_rel)  # optional, in case you want phone/email
        )
        .filter(Pembelian.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(404, "Invoice not found")

    # build the context exactly as your template expects:
    return templates.TemplateResponse(
        "invoice.html",       # your Jinja2 file
        {
            "request": request,  # always pass the request
            "invoice": {
                "number":       invoice.no_pembelian,
                "date":         invoice.sales_date.strftime("%d %B %Y"),
                "due_date":     invoice.sales_due_date.strftime("%d %B %Y"),
                "status":       invoice.status_pembayaran.value,
                "items": [
                    {
                        "description": item.item_name,
                        "quantity":    item.qty,
                        "unit":        item.satuan_name,
                        "tax_percent": item.tax_percentage,
                        "unit_price":  float(item.unit_price),
                        "total":       float(item.total_price),
                        "image_url":   item.item_rel.image_url if item.item_rel else None,
                    }
                    for item in invoice.pembelian_items
                ],
                "subtotal":            float(invoice.total_price),
                "discount":            float(invoice.discount),
                "additional_discount": float(invoice.additional_discount),
                "tax_amount":          float(invoice.total_price) * 0.1,  # or your formula
                "expense":             float(invoice.expense),
                "total":               float(invoice.total_price)
                                       - float(invoice.discount)
                                       - float(invoice.additional_discount),
                "grand_total":         float(invoice.total_price)
                                       - float(invoice.discount)
                                       - float(invoice.additional_discount)
                                       + float(invoice.expense),
            },
            "customer": {
                "name":  invoice.customer_display,
                "phone": invoice.customer_rel.phone if invoice.customer_rel else "–",
            },
        },
    )