import os
from fastapi import Request


def generate_attachment_url(file_path: str, request: Request = None) -> str:
    """Generate attachment URL based on environment"""
    clean_path = file_path.replace("\\", "/").replace("uploads/", "")
    
    if request:
        # Use request to build URL (works for both local and VPS)
        base_url = f"{request.url.scheme}://{request.url.netloc}"
        return f"{base_url}/static/{clean_path}"
    else:
        # Fallback to environment variable or default
        base_url = os.getenv("BASE_URL", "http://localhost:8000")
        return f"{base_url}/static/{clean_path}"