# In your schemas.py or a new file like response_models.py
from pydantic import BaseModel
from typing import List, Optional, Generic, TypeVar

# A generic type variable to make the PaginatedResponse reusable for different data types
T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    """
    A generic Pydantic model for paginated responses.
    `data` will be a list of items of type T.
    `total` will be the total count of items.
    """
    data: List[T]
    total: int

    # You can add more fields here if you need more pagination metadata, e.g.:
    # skip: int
    # limit: int
    # current_page: int
    # total_pages: int