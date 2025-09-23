import os
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI,  APIRouter

from fastapi.params import Depends
from jwt import ExpiredSignatureError, InvalidTokenError
import jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette import status

from starlette.exceptions import HTTPException

from schemas.PaginatedResponseSchemas import PaginatedResponse
from schemas.UserSchemas import UserCreate, TokenSchema, RequestDetails, UserOut, UserUpdate, UserType
from database import  get_db
from utils import get_hashed_password, verify_password, create_access_token, create_refresh_token
from models.User import User

router =APIRouter()


class RefreshTokenRequest(BaseModel):
    refresh_token: str

class RefreshTokenResponse(BaseModel):
    access_token: str


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

    # Mengatur waktu login ke WIB (UTC+7)
    indonesian_timezone = ZoneInfo("Asia/Jakarta")
    user.last_login = datetime.now(indonesian_timezone)

    hashed_pass = user.password
    if not verify_password(request.password, hashed_pass):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password atau username salah"
        )

    access=create_access_token(user.id, user.username)
    refresh = create_refresh_token(user.id, user.username)
    db.commit()
    db.refresh(user)

    return {
        "access_token": access,
        "refresh_token": refresh,
    }


@router.post('/refresh', response_model=RefreshTokenResponse)
def refresh_token(request: RefreshTokenRequest, db: Session = Depends(get_db)):
    try:
        # You'll need to add JWT_REFRESH_SECRET_KEY to your environment
        # or use the same secret as access tokens
        JWT_REFRESH_SECRET_KEY = os.getenv('JWT_REFRESH_SECRET_KEY') or os.getenv('JWT_SECRET_KEY')
        ALGORITHM = "HS256"
        
        # Decode refresh token
        payload = jwt.decode(
            request.refresh_token, 
            JWT_REFRESH_SECRET_KEY, 
            algorithms=[ALGORITHM]
        )
        user_id = payload.get("sub")
        
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="Invalid refresh token"
            )
        
        # Check if user still exists and is active
        user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, 
                detail="User not found or inactive"
            )
        
        # Create new access token
        new_access_token = create_access_token(user.id)
        
        return {
            "access_token": new_access_token
        }
        
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Refresh token expired"
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid refresh token"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Token refresh failed"
        )