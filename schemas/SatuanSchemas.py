from pydantic import BaseModel

class SatuanBase(BaseModel):
    name: str
    symbol: str
    is_active: bool = True

class SatuanCreate(SatuanBase):
    pass

class SatuanUpdate(SatuanBase):
    pass

class SatuanOut(SatuanBase):
    id: int

    class Config:
        orm_mode = True
