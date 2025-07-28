import os
from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException
from schemas.UserSchemas import UserCreate, TokenSchema, RequestDetails
from database import Base, engine, SessionLocal, get_db
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
    user = db.query(User).filter(User.username == request.username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password atau username salah")
    hashed_pass = user.password
    if not verify_password(request.password, hashed_pass):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password atau username salah"
        )

    access=create_access_token(user.id)
    refresh = create_refresh_token(user.id)

    return {
        "access_token": access,
        "refresh_token": refresh,
    }


@router.get("/test-ci")
def testCI(db:Session = Depends(get_db)):
    return {
        "message" : "HALLO, TEST 123"
    }