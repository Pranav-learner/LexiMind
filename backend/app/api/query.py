from fastapi import APIRouter
from pydantic import BaseModel

from app.services.embedding_service import generate_embedding
from app.api.upload import vector_store
from app.services.answer_service import generate_answer, format_sources

router = APIRouter(prefix="/query", tags=["query"])

class QueryRequest(BaseModel):
    question: str


@router.post("")
def query_knowledge(req: QueryRequest):

    # 1️⃣ Convert question to embedding
    query_embedding = generate_embedding(req.question)

    # 2️⃣ Retrieve top relevant chunks
    relevant_chunks = vector_store.search(
        query_embedding,
        top_k=5
    )

    # 3️⃣ Generate answer
    answer = generate_answer(req.question, relevant_chunks)

    # 4️⃣ Format citations cleanly
    sources = format_sources(relevant_chunks)

    return {
        "question": req.question,
        "answer": answer,
        "sources": sources
    }

