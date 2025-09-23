from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any, List

# id = Column(Integer, primary_key=True, index=True)
# entity_id = Column(String(100), nullable=False)  # ID of the thing being tracked
# entity_type = Column(Enum(AuditEntityEnum), nullable=False)  # Type of entity
# description = Column(Text, nullable=False)  # What happened (human-readable)
# user_name = Column(String(100), nullable=False)  # Who did it
# timestamp = Column(DateTime, default=datetime.now, nullable=False)

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