
# models/mixin/AuditMixin.py
from typing import Dict, Any, Optional
from sqlalchemy import event
from sqlalchemy.orm import Session


class AuditMixin:
    """
    Mixin to add audit trail functionality to models.
    Add this to models that need automatic audit tracking.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Register event listeners for this model
        event.listen(cls, 'after_insert', cls._audit_after_insert)
        event.listen(cls, 'after_update', cls._audit_after_update)
        event.listen(cls, 'after_delete', cls._audit_after_delete)

    @classmethod
    def _audit_after_insert(cls, mapper, connection, target):
        """Called after a new record is inserted"""
        # This would be called from your service layer with proper context
        pass

    @classmethod
    def _audit_after_update(cls, mapper, connection, target):
        """Called after a record is updated"""
        # This would be called from your service layer with proper context
        pass

    @classmethod
    def _audit_after_delete(cls, mapper, connection, target):
        """Called after a record is deleted"""
        # This would be called from your service layer with proper context
        pass

    def get_audit_changes(self, original_values: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Compare current values with original values to detect changes.
        Returns dict of changed fields with old/new values.
        """
        changes = {}

        for attr, old_value in original_values.items():
            if hasattr(self, attr):
                new_value = getattr(self, attr)
                if old_value != new_value:
                    changes[attr] = {
                        'old': old_value,
                        'new': new_value
                    }

        return changes


# Helper decorator for service methods
def audit_action(action_type: str, entity_type: str):
    """
    Decorator to automatically log audit trails for service methods.

    Usage:
    @audit_action("CREATE", "PEMBELIAN")
    def create_pembelian(self, data, user_name: str, user_id: int = None):
        # Your service logic here
        pass
    """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            # Extract user context
            user_name = kwargs.get('user_name')
            user_id = kwargs.get('user_id')

            result = func(self, *args, **kwargs)

            # Log audit trail if we have the necessary context
            if hasattr(self, 'audit_service') and user_name:
                # This would need to be customized based on your specific needs
                pass

            return result
        return wrapper
    return decorator