from datetime import datetime

from pydantic import BaseModel

class SatuanBase(BaseModel):
    name: str
    symbol: str
    is_active: bool = True
    created_at: datetime

class SatuanCreate(SatuanBase):
    pass

class SatuanUpdate(SatuanBase):
    pass

class SatuanOut(SatuanBase):
    id: int

    class Config:
        from_attributes = True
