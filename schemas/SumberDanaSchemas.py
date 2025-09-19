from datetime import datetime

from pydantic import BaseModel

class SumberDanaBase(BaseModel):
    name: str
    is_active: bool = True


class SumberDanaCreate(SumberDanaBase):
    pass

class SumberDanaUpdate(SumberDanaBase):
    pass

class SumberDanaOut(SumberDanaBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
