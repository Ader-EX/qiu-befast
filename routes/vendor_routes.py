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
from utils import soft_delete_record

router = APIRouter()
@router.get("", response_model=PaginatedResponse[VendorOut])
def get_all_vendors(
        db: Session = Depends(get_db),
        page: int = 1,
        rowsPerPage: int = 10,
        is_active: Optional[bool] = None,
        contains_deleted: Optional[bool] = False, 
        search_key: Optional[str] = None,
):
    query = db.query(Vendor).options(joinedload(Vendor.top_rel), joinedload(Vendor.curr_rel))
    if contains_deleted is False:
        query = query.filter(Vendor.is_deleted == False)
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


def generate_vendor_id_with_counter(db: Session) -> str:
    """
    Alternative approach using a simple counter.
    This version counts all vendors (including deleted ones) to ensure uniqueness.
    """
    # Count total vendors to determine next ID
    vendor_count = db.query(Vendor).count()
    next_number = vendor_count + 1
    
    # Keep incrementing if ID already exists (handles edge cases)
    while True:
        vendor_id = f"VEN-{next_number:05d}"
        existing = db.query(Vendor).filter(Vendor.id == vendor_id).first()
        if not existing:
            return vendor_id
        next_number += 1
        
@router.post("", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(data: VendorCreate, db: Session = Depends(get_db)):
    # Validate foreign key relationships
    if not db.query(Currency).filter(Currency.id == data.currency_id).first():
        raise HTTPException(400, f"Currency with ID '{data.currency_id}' not found.")
    if not db.query(TermOfPayment).filter(TermOfPayment.id == data.top_id).first():
        raise HTTPException(400, f"Term of Payment with ID '{data.top_id}' not found.")
    
    # Generate vendor ID if not provided in data
    if not hasattr(data, 'id') or not data.id:
        vendor_id = generate_vendor_id_with_counter(db)
    else:
        vendor_id = data.id
    
    # Check if vendor already exists
    existing_vendor = db.query(Vendor).filter(Vendor.id == vendor_id).first()
    
    if existing_vendor:
        if existing_vendor.is_deleted:
            # Restore deleted vendor
            for field, value in data.dict(exclude={'id'}).items():
                setattr(existing_vendor, field, value)
            existing_vendor.is_deleted = False
            existing_vendor.deleted_at = None
            db.commit()
            db.refresh(existing_vendor)
            return existing_vendor
        else:
            raise HTTPException(400, "Vendor ID already exists")
    
    # Create new vendor
    vendor_data = data.dict()
    vendor_data['id'] = vendor_id  # Set the generated ID
    vendor = Vendor(**vendor_data)
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
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.is_deleted == False).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    soft_delete_record(db, Vendor, vendor_id)

    db.commit()
    return None