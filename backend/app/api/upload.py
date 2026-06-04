import os

from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.core.state import bm25_retriever, vector_store
from app.services.ingestion_service import ingest_pdf

router = APIRouter(prefix="/upload", tags=["upload"])

UPLOAD_DIR = settings.upload_dir
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Ingestion (extract -> chunk -> enrich metadata -> batch embed -> index) lives in
    # the ingestion service; the route only handles transport.
    return ingest_pdf(file_path, file.filename, vector_store, bm25_retriever)
