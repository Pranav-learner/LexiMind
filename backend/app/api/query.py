from fastapi import APIRouter
from pydantic import BaseModel

from app.services.embedding_service import generate_embedding
from app.api.upload import vector_store
from app.services.answer_service import generate_answer

router  = APIRouter(prefix="/query", tags=["query"])

class QueryRequest(BaseModel):
    question: str

@router.post("")
def query_knowledge(req: QueryRequest):
    # Convert question to embedding
    query_embedding = generate_embedding(req.question)

    # Retrive top relevent chunks
    relevent_chunks = vector_store.search(
        query_embedding,
        top_k=5
    )

    #Genertae final asnwer using retrieved chunks
    answer = generate_answer(req.question,relevent_chunks)

    return {
        "question" : req.question,
        "answer": answer,
        "sources": relevent_chunks  # later use for citation
    }
