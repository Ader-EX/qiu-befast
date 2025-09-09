import os
import random
import time

from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Union, Any
from sqlalchemy import and_
from sqlalchemy.orm import Session
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


def soft_delete_record(session: Session, model_class, record_id):
    obj = session.get(model_class, record_id)
    if not obj:
        raise ValueError(f"{model_class.__name__} with id {record_id} not found")
    if hasattr(obj, "soft_delete"):
        obj.soft_delete()
    else:
        raise ValueError(f"{model_class.__name__} does not support soft delete")
    session.commit()
import time
import random
from datetime import datetime
from sqlalchemy import and_
from sqlalchemy.orm import Session

def generate_unique_record_number(
        db: Session,
        model_class,
        prefix: str = "QP/SI",
        max_retries: int = 5
) -> str:
    """Generate unique record number for any model with soft delete support.

    Format: PREFIX/NoUrut/MM/YYYY
    Sequence resets every month.
    
    Args:
        db: Database session
        model_class: The model class to check against
        prefix: Prefix for the record number
        max_retries: Maximum number of retries if collision occurs
    
    Returns:
        Unique record number string
        
    Raises:
        Exception: If unable to generate unique number after max_retries
    """
    
    today = datetime.now()
    bulan = today.strftime("%m")
    tahun = today.strftime("%Y")
    
    start_of_month = datetime(today.year, today.month, 1)
    if today.month == 12:
        start_of_next_month = datetime(today.year + 1, 1, 1)
    else:
        start_of_next_month = datetime(today.year, today.month + 1, 1)
    
    # Determine which field contains the record number
    record_number_field = None
    if hasattr(model_class, 'no_pembelian'):
        record_number_field = model_class.no_pembelian
    elif hasattr(model_class, 'no_penjualan'):
        record_number_field = model_class.no_penjualan
    elif hasattr(model_class, 'no_pembayaran'):
        record_number_field = model_class.no_pembayaran
    elif hasattr(model_class, 'no_pengembalian'):
        record_number_field = model_class.no_pengembalian
    elif hasattr(model_class, 'record_number'):
        record_number_field = model_class.record_number
    
    if record_number_field is None:
        raise Exception(f"Model {model_class.__name__} does not have a recognized record number field")
    
    prefix_part = prefix.split('/')[0]  # Get first part of prefix for comparison
    pattern = f"{prefix}/%/{bulan}/{tahun}"
    
    for attempt in range(max_retries):
        try:
            # Get all existing record numbers for this month/year pattern
            # We'll be more flexible with the date filter to catch edge cases
            existing_numbers_query = (
                db.query(record_number_field)
                .filter(
                    record_number_field.like(pattern)
                )
            )
            
            existing_numbers = existing_numbers_query.all()
            
            # Extract sequence numbers from existing records
            max_seq = 0
            for (record_number,) in existing_numbers:  # Note: query returns tuples
                if record_number:
                    try:
                        parts = record_number.split('/')
                        # Check if it matches our pattern: PREFIX/NoUrut/MM/YYYY
                        if (len(parts) >= 4 and 
                            parts[0] == prefix_part and 
                            parts[2] == bulan and 
                            parts[3] == tahun):
                            seq_num = int(parts[1])
                            max_seq = max(max_seq, seq_num)
                    except (ValueError, IndexError, TypeError):
                        continue
            
            # Generate next sequence number
            nomor_urut = max_seq + 1
            record_number = f"{prefix}/{nomor_urut:03d}/{bulan}/{tahun}"
            
            # Double-check that this exact record number doesn't exist
            existing_check = db.query(model_class).filter(
                record_number_field == record_number
            ).first()
            
            if not existing_check:
                return record_number
            else:
                # If it exists, continue to next iteration to try max_seq + 2, etc.
                print(f"Attempt {attempt + 1}: Record number {record_number} already exists, retrying...")
                continue
                
        except Exception as e:
            print(f"Attempt {attempt + 1} failed with error: {str(e)}")
            if attempt == max_retries - 1:
                # For debugging, let's provide more info
                try:
                    total_records = db.query(model_class).count()
                    records_this_month = db.query(model_class).filter(
                        and_(
                            model_class.created_at >= start_of_month,
                            model_class.created_at < start_of_next_month
                        )
                    ).count()
                    
                    raise Exception(
                        f"Failed to generate unique record number after {max_retries} attempts. "
                        f"Last error: {str(e)}. "
                        f"Total records: {total_records}, "
                        f"Records this month: {records_this_month}, "
                        f"Pattern: {pattern}, "
                        f"Field: {record_number_field.name if record_number_field else 'None'}"
                    )
                except:
                    raise Exception(f"Failed to generate unique record number after {max_retries} attempts: {str(e)}")
            
            # Add small random delay to reduce collision probability
            time.sleep(0.01 + random.uniform(0, 0.05))
    
    raise Exception(f"Failed to generate unique record number after {max_retries} attempts")


def generate_unique_record_number(
        db: Session,
        model_class,
        prefix: str = "QP/SI"
) -> str:
    """Generate unique record number by incrementing until we find one that doesn't exist."""
    
    today = datetime.now()
    bulan = today.strftime("%m")
    tahun = today.strftime("%Y")
    
    # Determine which field contains the record number
    record_number_field = None
    if hasattr(model_class, 'no_pembelian'):
        record_number_field = model_class.no_pembelian
    elif hasattr(model_class, 'no_penjualan'):
        record_number_field = model_class.no_penjualan
    elif hasattr(model_class, 'no_pembayaran'):
        record_number_field = model_class.no_pembayaran
    elif hasattr(model_class, 'no_pengembalian'):
        record_number_field = model_class.no_pengembalian
    elif hasattr(model_class, 'record_number'):
        record_number_field = model_class.record_number
    
    if record_number_field is None:
        raise Exception(f"Model {model_class.__name__} does not have a recognized record number field")
    
    max_seq = 0
    pattern = f"{prefix}/%/{bulan}/{tahun}"
    existing_numbers = db.query(record_number_field).filter(
        record_number_field.like(pattern)
    ).all()

    for (record_number,) in existing_numbers:
        if record_number:
            try:
                parts = record_number.split('/')
                if len(parts) >= 4 and parts[2] == bulan and parts[3] == tahun:
                    seq_num = int(parts[1])
                    max_seq = max(max_seq, seq_num)
            except:
                continue

    # Start checking from max+1
    nomor_urut = max_seq + 1
    while True:
        record_number = f"{prefix}/{nomor_urut:03d}/{bulan}/{tahun}"
        
        # Check if this exact record number exists in the database
        existing = db.query(model_class).filter(
            record_number_field == record_number
        ).first()
        
        if not existing:
            return record_number
        
        nomor_urut += 1
        
        # Safety check to prevent infinite loop
        if nomor_urut > 9999:
            raise Exception(f"Could not generate unique record number - exceeded limit of 9999")
    
    return record_number

def get_record_number_field_name(model_class):
    """Helper function to get the record number field name for a given model."""
    if hasattr(model_class, 'no_pembelian'):
        return 'no_pembelian'
    elif hasattr(model_class, 'no_penjualan'):
        return 'no_penjualan'
    elif hasattr(model_class, 'no_pembayaran'):
        return 'no_pembayaran'
    elif hasattr(model_class, 'no_pengembalian'):
        return 'no_pengembalian'
    elif hasattr(model_class, 'record_number'):
        return 'record_number'
    else:
        return None


def generate_unique_record_code(
        db: Session,
        model_class,
      
        prefix: str = "FG"
) -> str:
    """Generate unique record number for any model  column.

    Format: PREFIX-00001
 
    """
    counter =  db.query(model_class).count()

    nomor_urut = counter + 1
    return f"{prefix}-{nomor_urut:05d}"
