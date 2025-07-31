from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from starlette import status
from starlette.exceptions import HTTPException

from models.Customer import Customer
from schemas.CustomerSchemas import CustomerOut, CustomerCreate, CustomerUpdate
from database import get_db
from schemas.PaginatedResponseSchemas import PaginatedResponse

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
    query = db.query(Customer).options(joinedload(Customer.top_rel), joinedload(Customer.curr_rel))

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
    if db.query(Customer).filter(Customer.id == customer_data.id).first():
        raise HTTPException(status_code=400, detail="Customer with this ID already exists")

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

    db.delete(customer)
    db.commit()
    return None
