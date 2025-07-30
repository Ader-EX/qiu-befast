from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional

from database import get_db
from models.Currency import Currency
from models.TermOfPayment import TermOfPayment
from models.Vendor import Vendor
from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.VendorSchemas import VendorCreate, VendorUpdate, VendorOut

router = APIRouter()
@router.get("", response_model=PaginatedResponse[VendorOut])
def get_all_vendors(
        db: Session = Depends(get_db),
        page: int = 1,
        rowsPerPage: int = 10,
        is_active: Optional[bool] = None,
        search_key: Optional[str] = None,
):
    query = db.query(Vendor).options(joinedload(Vendor.top_rel), joinedload(Vendor.curr_rel))

    if is_active is not None:
        query = query.filter(Vendor.is_active == is_active)

    if search_key is not None:
        query = query.filter(or_(
            Vendor.name.ilike(f"%{search_key}%"),
            Vendor.id.ilike(f"%{search_key}%")
        ))

    total_count = query.count()

    paginated_data = (
        query.offset((page - 1) * rowsPerPage)
        .limit(rowsPerPage)
        .all()
    )

    return {
        "data": paginated_data,
        "total": total_count,
    }

@router.get("/{vendor_id}", response_model=VendorOut)
def get_vendor(vendor_id: str, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).options(joinedload(Vendor.top_rel), joinedload(Vendor.curr_rel)).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendor

@router.post("", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(data: VendorCreate, db: Session = Depends(get_db)):
    # 1. Check if Vendor ID already exists
    existing_vendor = db.query(Vendor).filter(Vendor.id == data.id).first()
    if existing_vendor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vendor with ID '{data.id}' already exists."
        )

    # 2. Check if currency_id exists
    currency = db.query(Currency).filter(Currency.id == data.currency_id).first()
    if not currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Currency with ID '{data.currency_id}' not found."
        )

    # 3. Check if top_id exists
    top = db.query(TermOfPayment).filter(TermOfPayment.id == data.top_id).first()
    if not top:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Term of Payment with ID '{data.top_id}' not found."
        )

    # If all valid, create the vendor
    vendor = Vendor(**data.dict())
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor

@router.put("/{vendor_id}", response_model=VendorOut)
def update_vendor(vendor_id: str, data: VendorUpdate, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    for key, value in data.dict().items():
        setattr(vendor, key, value)

    db.commit()
    db.refresh(vendor)
    return vendor

@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vendor(vendor_id: str, db: Session = Depends(get_db)):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    db.delete(vendor)
    db.commit()
    return None
