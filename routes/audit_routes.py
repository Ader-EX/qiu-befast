# routers/audit.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
from models.AuditTrail import AuditTrail, AuditEntityEnum

router = APIRouter()

@router.get("")
def get_audit_trails(
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,

        user_name: Optional[str] = None,
        limit: int = Query(50, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    query = db.query(AuditTrail)

    if entity_type:
        query = query.filter(AuditTrail.entity_type == entity_type.upper())
    if entity_id:
        query = query.filter(AuditTrail.entity_id == entity_id)

    if user_name:
        query = query.filter(AuditTrail.user_name.ilike(f"%{user_name}%"))

    query = query.order_by(AuditTrail.timestamp.desc())
    total = query.count()
    items = query.offset(offset).limit(limit).all()

    return {
        "total": total,
        "items": items,
        "limit": limit,
        "offset": offset
    }

@router.get("/{entity_type}/{entity_id}")
def get_entity_audit_trail(
        entity_type: AuditEntityEnum,
        entity_id: str,
        limit: int = Query(50, le=1000),
        offset: int = Query(0, ge=0),
        db: Session = Depends(get_db)
):
    query = db.query(AuditTrail).filter(
        AuditTrail.entity_type == entity_type,
        AuditTrail.entity_id == entity_id
    ).order_by(AuditTrail.timestamp.desc())

    total = query.count()
    items = query.offset(offset).limit(limit).all()
    formatted_items = [
        {
            **item.__dict__,
            "timestamp": item.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }
        for item in items
    ]

    return {
        "total": total,
        "items": formatted_items,
        "limit": limit,
        "offset": offset
    }