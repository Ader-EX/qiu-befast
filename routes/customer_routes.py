from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from starlette import status
from starlette.exceptions import HTTPException

from models.Currency import Currency
from models.Customer import Customer
from schemas.CustomerSchemas import CustomerOut, CustomerCreate, CustomerUpdate
from database import get_db
from schemas.PaginatedResponseSchemas import PaginatedResponse
from utils import soft_delete_record

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
):
    query = db.query(Customer).options( joinedload(Customer.curr_rel))

    if contains_deleted is False :
        query = query.filter(Customer.is_deleted == False)
    if is_active is not None:
        query = query.filter(Customer.is_active == is_active)

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
# Get one
@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(customer_id: str, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer

# Create
def generate_customer_code_with_counter(db: Session) -> str:
    """
    Alternative approach using a simple counter.
    This version counts all customers (including deleted ones) to ensure uniqueness.
    """
    # Count total customers to determine next code
    customer_count = db.query(Customer).count()
    next_number = customer_count + 1
    
    # Keep incrementing if code already exists (handles edge cases)
    while True:
        customer_code = f"CUS-{next_number:05d}"
        existing = db.query(Customer).filter(Customer.code == customer_code).first()
        if not existing:
            return customer_code
        next_number += 1
        
@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(customer_data: CustomerCreate, db: Session = Depends(get_db)):
    # Generate customer code if not provided in data
    if not hasattr(customer_data, 'code') or not customer_data.code:
        customer_code = generate_customer_code_with_counter(db)
    else:
        customer_code = customer_data.code
    
    # 🔍 Check if customer with same code exists (active OR deleted)
    existing_customer = db.query(Customer).filter(Customer.code == customer_code).first()

    if existing_customer:
        if existing_customer.is_deleted:
            # ✅ Revive soft-deleted customer
            for field, value in customer_data.dict(exclude={'code'}).items():
                setattr(existing_customer, field, value)
            existing_customer.is_deleted = False
            existing_customer.deleted_at = None
            existing_customer.is_active = True
            db.commit()
            db.refresh(existing_customer)
            return existing_customer

        else:
            # ❌ Prevent duplicate active codes
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Customer dengan code '{customer_code}' sudah ada."
            )

    # 🔍 Validate currency
    currency = db.query(Currency).filter(
        Currency.id == customer_data.currency_id,
        Currency.is_active == True
    ).first()
    if not currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Currency with ID '{customer_data.currency_id}' not found."
        )

    # ✅ Create a new customer with generated code
    customer_dict = customer_data.dict()
    customer_dict['code'] = customer_code  # Set the generated code
    customer = Customer(**customer_dict)
    db.add(customer)
    db.commit()
    db.refresh(customer)

    return customer


# Update
@router.put("/{customer_id}", response_model=CustomerOut)
async def update_customer(customer_id: str, customer_data: CustomerUpdate, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    for field, value in customer_data.dict().items():
        setattr(customer, field, value)

    db.commit()
    db.refresh(customer)
    return customer

# Delete
@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer(customer_id: str, db: Session = Depends(get_db)):

    customer = db.query(Customer).filter(Customer.id == customer_id).first()

    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    soft_delete_record(db, Customer, customer_id)
    db.commit()
    return None
