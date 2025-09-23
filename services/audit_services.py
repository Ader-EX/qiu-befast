import json
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from fastapi import Request, Depends

from models.AuditTrail import AuditTrail, AuditEntityEnum



class AuditService:
    def __init__(self, db: Session):
        self.db = db


    def default_log(  self,
              entity_id: str,
              entity_type: AuditEntityEnum,
              description: str,
              user_name: str ):

        audit_entry = AuditTrail(
            entity_id=entity_id,
            entity_type=entity_type,
            description=description,
            user_name=user_name
        )
        self.db.add(audit_entry)
        self.db.commit()
        return audit_entry


