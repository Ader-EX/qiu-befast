from datetime import datetime
from sqlalchemy import Boolean, DateTime, Column
from sqlalchemy.orm import RelationshipProperty

class SoftDeleteMixin:
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    def soft_delete(self, visited=None):
        """
        Soft delete this object and all related objects that have the same method.
        Prevents infinite recursion using `visited` set.
        """
        if visited is None:
            visited = set()

        if id(self) in visited:
            return
        visited.add(id(self))

        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

        for attr in dir(self):
            rel = getattr(type(self), attr, None)
            if isinstance(rel, RelationshipProperty):
                related = getattr(self, attr)
                if related is None:
                    continue
                if isinstance(related, list):
                    for obj in related:
                        if hasattr(obj, "soft_delete"):
                            obj.soft_delete(visited)
                else:
                    if hasattr(related, "soft_delete"):
                        related.soft_delete(visited)