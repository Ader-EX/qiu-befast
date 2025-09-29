from datetime import datetime, date, time
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, exists
from sqlalchemy.orm import Session, joinedload
from starlette import status
from starlette.exceptions import HTTPException

from models.AuditTrail import AuditEntityEnum
from models.Currency import Currency
from models.Customer import Customer
from models.KodeLambung import KodeLambung
from schemas.CustomerSchemas import CustomerOut, CustomerCreate, CustomerUpdate
from database import get_db
from schemas.PaginatedResponseSchemas import PaginatedResponse
from services.audit_services import AuditService
from utils import soft_delete_record, get_current_user_name, generate_incremental_id

router = APIRouter()

# Get all
@router.get("", response_model=PaginatedResponse[CustomerOut])
def get_all_Customer(
        db: Session = Depends(get_db),
        page: int = 1,
        rowsPerPage: int = 10,
        contains_deleted: Optional[bool] = False,
        is_active: Optional[bool] = None,
        search_key: Optional[str] = None,
        to_date : Optional[date] = Query(None, description="Filter by date"),
        from_date : Optional[date] = Query(None, description="Filter by date")
):
    query = db.query(Customer).options(
        joinedload(Customer.curr_rel),
        joinedload(Customer.kode_lambung_rel)
    )
    if contains_deleted is False :
        query = query.filter(Customer.is_deleted == False)
    if is_active is not None:
        query = query.filter(Customer.is_active == is_active)
    if from_date and to_date:
        query = query.filter(
            Customer.created_at.between(
                datetime.combine(from_date, time.min),
                datetime.combine(to_date, time.max),
            )
        )
    elif from_date:
        query = query.filter(Customer.created_at >= datetime.combine(from_date, time.min))
    elif to_date:
        query = query.filter(Customer.created_at <= datetime.combine(to_date, time.max))
    if search_key is not None:
        query = query.filter(or_(
            Customer.name.ilike(f"%{search_key}%"),
            Customer.id.ilike(f"%{search_key}%")
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

@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(
        customer_id: str,
        db: Session = Depends(get_db),
        contains_deleted: Optional[bool] = False
):
    query = db.query(Customer).filter(Customer.id == customer_id)

    if not contains_deleted:
        query = query.filter(Customer.is_deleted == False)

    customer = query.one_or_none()

    if customer is None:
        raise HTTPException(
            status_code=404,
            detail=f"Customer with ID '{customer_id}' not found"
        )

    if contains_deleted:
        kode_lambung_records = db.query(KodeLambung).filter(
            KodeLambung.customer_id == customer.id
        ).all()
    else:
        kode_lambung_records = db.query(KodeLambung).filter(
            KodeLambung.customer_id == customer.id,
            KodeLambung.is_deleted.is_(False)
        ).all()

    response_data = {
        "id": customer.id,
        "code": customer.code,
        "name": customer.name,
        "address": customer.address,
        "is_active": customer.is_active,
        "currency_id": customer.currency_id,
        "created_at": customer.created_at,
        "curr_rel": customer.curr_rel,
        "kode_lambung_rel": kode_lambung_records
    }

    return response_data

@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(customer_data: CustomerCreate, db: Session = Depends(get_db), user_name: str = Depends(get_current_user_name)):

    if not hasattr(customer_data, 'code') or not customer_data.code:
        customer_code = generate_incremental_id(db, Customer, prefix="CUS-")
    else:
        customer_code = customer_data.code

    audit_service = AuditService(db)

    existing_customer = db.query(Customer).filter(Customer.code == customer_code).first()

    if existing_customer:
        if existing_customer.is_deleted:
            for field, value in customer_data.dict(exclude={'code', 'kode_lambungs'}).items():
                setattr(existing_customer, field, value)
            existing_customer.is_deleted = False
            existing_customer.deleted_at = None
            existing_customer.is_active = True

            if customer_data.kode_lambungs:
                for kl_name in customer_data.kode_lambungs:
                    kode_lambung = KodeLambung(name=kl_name, customer_id=existing_customer.id)
                    db.add(kode_lambung)

            audit_service.default_log(
                entity_id=existing_customer.id,
                entity_type=AuditEntityEnum.CUSTOMER,
                description=f"Customer {existing_customer.name} telah dipulihkan",
                user_name=user_name
            )
            db.commit()
            db.refresh(existing_customer)
            return existing_customer

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Customer dengan code '{customer_code}' sudah ada."
            )

    # Validate currency exists
    currency = db.query(Currency).filter(
        Currency.id == customer_data.currency_id,
        Currency.is_active == True
    ).first()
    if not currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Currency with ID '{customer_data.currency_id}' not found."
        )

    # Create new customer
    customer_dict = customer_data.dict(exclude={'kode_lambungs'})
    customer_dict['code'] = customer_code
    customer = Customer(**customer_dict)

    db.add(customer)
    db.flush()

    audit_service.default_log(
        entity_id=customer.id,
        entity_type=AuditEntityEnum.CUSTOMER,
        description=f"Customer {customer.name} telah dibuat",
        user_name=user_name
    )

    if customer_data.kode_lambungs:
        for kl_name in customer_data.kode_lambungs:
            kode_lambung = KodeLambung(name=kl_name, customer_id=customer.id)
            db.add(kode_lambung)

    db.commit()
    db.refresh(customer)
    return customer

@router.put("/{customer_id}", response_model=CustomerOut)
async def update_customer(customer_id: str, customer_data: CustomerUpdate, db: Session = Depends(get_db), user_name: str = Depends(get_current_user_name)):
    audit_service = AuditService(db)

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Update customer fields (excluding kode_lambungs)
    for field, value in customer_data.dict(exclude={'kode_lambungs'}).items():
        setattr(customer, field, value)

    # Handle kode_lambungs update
    if customer_data.kode_lambungs is not None:
        # Get all existing KodeLambung IDs for this customer
        existing_kode_lambungs = db.query(KodeLambung).filter(
            KodeLambung.customer_id == customer.id
        ).all()

        # Create a set of IDs that are being updated/kept
        provided_ids = set()

        # Process each KodeLambungUpdate object
        for kl_data in customer_data.kode_lambungs:
            if hasattr(kl_data, 'id') and kl_data.id:
                provided_ids.add(kl_data.id)
                existing_kode_lambung = db.query(KodeLambung).filter(
                    KodeLambung.id == kl_data.id,
                    KodeLambung.customer_id == customer.id  # Ensure it belongs to this customer
                ).first()

                if existing_kode_lambung:
                    # Update the name if provided
                    if hasattr(kl_data, 'name') and kl_data.name:
                        existing_kode_lambung.name = kl_data.name
                else:
                    # ID provided but not found, create new one
                    kode_lambung = KodeLambung(
                        name=kl_data.name,
                        customer_id=customer.id
                    )
                    db.add(kode_lambung)
            else:
                # No ID provided, create new KodeLambung
                kode_lambung = KodeLambung(
                    name=kl_data.name,
                    customer_id=customer.id
                )
                db.add(kode_lambung)

        for existing_kl in existing_kode_lambungs:
            if existing_kl.id not in provided_ids:
                soft_delete_record(db, KodeLambung, existing_kl.id)

    audit_service.default_log(
        entity_id=customer.id,
        entity_type=AuditEntityEnum.CUSTOMER,
        description=f"Data Customer {customer.name} telah diubah",
        user_name=user_name
    )

    db.commit()
    db.refresh(customer)
    return customer
@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(customer_id: str, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    soft_delete_record(db, Customer, customer_id)
    kode_lambungs = db.query(KodeLambung).filter(KodeLambung.customer_id == customer_id).all()
    for kl in kode_lambungs:
        soft_delete_record(db, KodeLambung, kl.id)

    db.commit()
    return None