# routes/kode_lambung_routes.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
from models.KodeLambung import KodeLambung
from schemas.KodeLambungSchema import KodeLambungCreate, KodeLambungUpdate, KodeLambungResponse
from schemas.PaginatedResponseSchemas import PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[KodeLambungResponse])
async def get_all_kode_lambung(
    search: Optional[str] = Query(None, description="Search by name"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get all kode lambung with pagination and search"""
    query = db.query(KodeLambung).filter(KodeLambung.is_deleted == False)
    
    if search:
        query = query.filter(KodeLambung.name.ilike(f"%{search}%"))
    
    query = query.order_by(KodeLambung.name)
    
    total = query.count()
    offset = (page - 1) * size
    items = query.offset(offset).limit(size).all()
    
    return {"data": items, "total": total}


@router.get("/all", response_model=List[KodeLambungResponse])
async def get_all_kode_lambung_no_pagination(db: Session = Depends(get_db)):
    """Get all kode lambung without pagination (for dropdowns)"""
    items = db.query(KodeLambung).filter(KodeLambung.is_deleted == False).order_by(KodeLambung.name).all()
    return items


@router.get("/{kode_lambung_id}", response_model=KodeLambungResponse)
async def get_kode_lambung(kode_lambung_id: int, db: Session = Depends(get_db)):
    """Get single kode lambung by ID"""
    kode_lambung = db.query(KodeLambung).filter(
        KodeLambung.id == kode_lambung_id,
        KodeLambung.is_deleted == False
    ).first()
    
    if not kode_lambung:
        raise HTTPException(status_code=404, detail="Kode Lambung not found")
    
    return kode_lambung


@router.post("", status_code=status.HTTP_201_CREATED, response_model=KodeLambungResponse)
async def create_kode_lambung(request: KodeLambungCreate, db: Session = Depends(get_db)):
    """Create new kode lambung"""
    # Check for duplicate name
    existing = db.query(KodeLambung).filter(
        KodeLambung.name == request.name,
        KodeLambung.is_deleted == False
    ).first()
    
    if existing:
        raise HTTPException(status_code=400, detail="Kode Lambung with this name already exists")
    
    kode_lambung = KodeLambung(name=request.name)
    db.add(kode_lambung)
    db.commit()
    db.refresh(kode_lambung)
    
    return kode_lambung


@router.put("/{kode_lambung_id}", response_model=KodeLambungResponse)
async def update_kode_lambung(
    kode_lambung_id: int, 
    request: KodeLambungUpdate, 
    db: Session = Depends(get_db)
):
    """Update kode lambung"""
    kode_lambung = db.query(KodeLambung).filter(
        KodeLambung.id == kode_lambung_id,
        KodeLambung.is_deleted == False
    ).first()
    
    if not kode_lambung:
        raise HTTPException(status_code=404, detail="Kode Lambung not found")
    
    update_data = request.dict(exclude_unset=True)
    
    # Check for duplicate name if name is being updated
    if "name" in update_data and update_data["name"] != kode_lambung.name:
        existing = db.query(KodeLambung).filter(
            KodeLambung.name == update_data["name"],
            KodeLambung.id != kode_lambung_id,
            KodeLambung.is_deleted == False
        ).first()
        
        if existing:
            raise HTTPException(status_code=400, detail="Kode Lambung with this name already exists")
    
    # Update fields
    for field, value in update_data.items():
        setattr(kode_lambung, field, value)
    
    db.commit()
    db.refresh(kode_lambung)
    
    return kode_lambung


@router.delete("/{kode_lambung_id}")
async def delete_kode_lambung(kode_lambung_id: int, db: Session = Depends(get_db)):
    """Soft delete kode lambung"""
    kode_lambung = db.query(KodeLambung).filter(
        KodeLambung.id == kode_lambung_id,
        KodeLambung.is_deleted == False
    ).first()
    
    if not kode_lambung:
        raise HTTPException(status_code=404, detail="Kode Lambung not found")
    
    # Check if it's being used in any penjualan
    from models.Penjualan import Penjualan
    in_use = db.query(Penjualan).filter(
        Penjualan.kode_lambung_id == kode_lambung_id,
        Penjualan.is_deleted == False
    ).first()
    
    if in_use:
        raise HTTPException(
            status_code=400, 
            detail="Cannot delete Kode Lambung as it is being used in existing Penjualan records"
        )
    
    # Soft delete
    kode_lambung.soft_delete()
    db.commit()
    
    return {"message": "Kode Lambung deleted successfully"}