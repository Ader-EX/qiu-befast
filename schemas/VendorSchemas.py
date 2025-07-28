from pydantic import BaseModel

class VendorBase(BaseModel):
    name: str
    address: str
    currency_id: int
    top_id: int
    is_active: bool = True

class VendorCreate(VendorBase):
    pass

class VendorUpdate(VendorBase):
    pass

class VendorOut(VendorBase):
    id: int

    class Config:
        orm_mode = True
