import os

from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Union, Any
import jwt

REFRESH_TOKEN_EXPIRE_MINUTES=60 * 24 * 7


password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_hashed_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, hashed_pass: str) -> bool:
    return password_context.verify(password, hashed_pass)

def create_access_token(subject: Union[str, Any], expires_delta: int = None) -> str:
    if expires_delta is not None:
        expires_delta = datetime.now() + expires_delta

    else:
        expires_delta = datetime.now() + timedelta(minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES",30)))


    to_encode = {"exp": expires_delta, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, os.getenv("JWT_SECRET_KEY"), os.getenv("ALGORITHM"))

    return encoded_jwt

def create_refresh_token(subject: Union[str, Any], expires_delta: int = None) -> str:
    if expires_delta is not None:
        expires_delta = datetime.now() + expires_delta
    else:
        expires_delta = datetime.now() + timedelta(minutes=REFRESH_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": expires_delta, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, os.getenv("JWT_REFRESH_SECRET_KEY"), os.getenv("ALGORITHM"))
    return encoded_jwt

def resolve_css_vars(css: str) -> str:
    css_vars = {
        '--ink': '#020617',
        '--muted': '#64748B',
        '--brand': '#FC440E',
        '--brand-12': 'rgba(251,68,15,0.12)',
        '--line': '#E2E8F0',
        '--danger': '#DC2626',
        '--bg': '#fff',
    }
    for var_name, value in css_vars.items():
        css = css.replace(f"var({var_name})", value)
    return css
