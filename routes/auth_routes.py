import os
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.UserSchemas import UserCreate, TokenSchema, RequestDetails, UserOut, UserUpdate, UserType
from database import  get_db
from utils import get_hashed_password, verify_password, create_access_token, create_refresh_token
from models.User import User

router =APIRouter()

@router.post("/register", status_code=status.HTTP_200_OK)
def register_user(user: UserCreate, session: Session = Depends(get_db)):
    existing_user = session.query(User).filter_by(username=user.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    encrypted_password =get_hashed_password(user.password)

    new_user = User(username=user.username, password=encrypted_password )

    session.add(new_user)
    session.commit()
    session.refresh(new_user)

    return {"message":"user created successfully"}


@router.post('/login' ,response_model=TokenSchema)
def login(request: RequestDetails, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == request.username, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password atau username salah")
    user.last_login = datetime.now()
    hashed_pass = user.password
    if not verify_password(request.password, hashed_pass):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password atau username salah"
        )

    access=create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    db.commit()
    db.refresh(user)

    return {
        "access_token": access,
        "refresh_token": refresh,
    }

@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    hashed = get_hashed_password(payload.password)
    user = User(username=payload.username, password=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.get("/users", response_model=PaginatedResponse[UserOut])
def list_users(skip: int = 0,
               limit: int = 50,
               is_active: Optional[bool] = None,
                search_key: Optional[str] = None,

               db: Session = Depends(get_db)):

    query = db.query(User)

    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if search_key:
        query = query.filter(User.username.ilike(f"%{search_key}%"))

    total_count = query.count()
    paginated_data = query.offset(skip).limit(limit).all()
    return {
        "data": paginated_data,
        "total": total_count
    }

@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")


    if payload.username and payload.username != user.username:
        if db.query(User).filter(User.username == payload.username).first():
            raise HTTPException(status_code=400, detail="Username already exists")
        user.username = payload.username

    if payload.password:
        user.password = get_hashed_password(payload.password)

    if payload.role is not None:
        user.role = payload.role

    db.commit()
    db.refresh(user)
    return user

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    return None