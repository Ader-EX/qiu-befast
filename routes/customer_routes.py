from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from starlette import status
from starlette.exceptions import HTTPException

from models.Currency import Currency
from models.Customer import Customer
from models.TermOfPayment import TermOfPayment
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
        is_active: Optional[bool] = None,
        search_key: Optional[str] = None,
):
    query = db.query(Customer).options(joinedload(Customer.top_rel), joinedload(Customer.curr_rel)).filter(Customer.is_deleted == False )

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
@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(customer_data: CustomerCreate, db: Session = Depends(get_db)):
    existing_customer = db.query(Customer).filter(Customer.id == customer_data.id).first()
    if existing_customer:
        if  existing_customer.is_active:
            for field, value in customer_data.dict().items():
                setattr(existing_customer, field, value)
            existing_customer.is_deleted = False
            existing_customer.deleted_at = None
            db.commit()
            db.refresh(existing_customer)
            return existing_customer
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Customer with ID '{customer_data.id}' already exists."
            )

    currency = db.query(Currency).filter(
        Currency.id == customer_data.currency_id,
        Currency.is_active == True
    ).first()
    if not currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Currency with ID '{customer_data.currency_id}' not found."
        )

    top = db.query(TermOfPayment).filter(
        TermOfPayment.id == customer_data.top_id,
        TermOfPayment.is_active == True
    ).first()
    if not top:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Term of Payment with ID '{customer_data.top_id}' not found."
        )

    customer = Customer(**customer_data.dict())
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
