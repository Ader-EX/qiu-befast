# schemas/KodeLambungSchema.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class KodeLambungBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class KodeLambungCreate(KodeLambungBase):
    pass


class KodeLambungUpdate(KodeLambungBase):
    id : Optional[int]
    name: str = Field(None, min_length=1, max_length=255)


class KodeLambungResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str