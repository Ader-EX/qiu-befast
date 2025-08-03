# routes/upload.py

from fastapi import APIRouter, UploadFile, File, HTTPException
import os
import shutil
from uuid import uuid4

router = APIRouter()

UPLOAD_DIR = os.getenv("UPLOAD_DIR" ,default="uploads/items")
os.makedirs(UPLOAD_DIR, exist_ok=True)  # Ensure dir exists

@router.post("/upload-image")
def upload_image(file: UploadFile = File(...)):
    ext = file.filename.split(".")[-1].lower()
    if ext not in ["jpg", "jpeg", "png", "webp"]:
        raise HTTPException(status_code=400, detail="Invalid file type")

    filename = f"{uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    relative_path = f"items/{filename}"

    return {
        "file_path": relative_path,
        "url": f"/static/{relative_path}"
    }
