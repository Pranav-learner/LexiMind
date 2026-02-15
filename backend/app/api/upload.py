from fastapi import APIRouter, File, UploadFile
import os
from app.services.pdf_service import extract_text_from_pdf
from app.services.chunking_service import chunk_text
from app.services.embedding_service import generate_embedding
from app.services.vector_store import VectorStore

# Global in-memory vector store (temporary for now)
vector_store = VectorStore(dimension=384)

router  = APIRouter(prefix="/upload", tags=["upload"])
UPLOAD_DIR = "uploaded_pdfs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        f.write(await file.read())

    extracted_pages = extract_text_from_pdf(file_path)  # first extract text from pdf file
    chunks = chunk_text(extracted_pages)  # make th chunks of the extracted page

    # After chunking
    for chunk in chunks:
        embedding = generate_embedding(chunk["text"])  # embedded each chunks 

        vector_store.add(   # stored in the vector database
            embedding,
            {
                "text": chunk["text"],
                "page_number": chunk["page_number"],
                "chunk_index": chunk["chunk_index"],
                "source": file.filename
            }
        )
        vector_store.save()
        print(f"Stored chunk {chunk['chunk_index']} from page {chunk['page_number']}")

    return {
        "filename": file.filename,
        "pages_extracted": len(extracted_pages),
        "total_chunks": len(chunks),
        "message": "PDF processed and indexed successfully"
    }


