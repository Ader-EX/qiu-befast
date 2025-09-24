from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any, List


class AuditTrailResponse(BaseModel):
    id: int
    user_name: str
    entity_type: str
    entity_id: str
    description: str
    timestamp: datetime

    class Config:
        orm_mode = True

class AuditTrailListResponse(BaseModel):
    total: int
    items: List[AuditTrailResponse]
    limit: int
    offset: int