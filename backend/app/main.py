from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.query import router as query_router
from app.analytics.api import router as analytics_router
from app.api.upload import router as upload_router
from app.auth.api import router as auth_router
from app.chat.api import router as chat_router
from app.citations.api import router as citations_router
from app.db.base import init_db
from app.documents.api import router as document_router
from app.documents.reading_api import router as reading_router
from app.flashcards.api import router as flashcards_router
from app.ingestion.api import router as ingestion_router
from app.mmcontext.api import router as mmcontext_router
from app.mmretrieval.api import router as mmsearch_router
from app.vision.api import router as vision_router
from app.notes.api import router as notes_router
from app.notes.api import tag_router as notes_tag_router
from app.summaries.api import router as summary_router
from app.workspaces.api import router as workspace_router

app = FastAPI(title="LexiMind API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    # Create the SQLite tables (users, workspaces) if they don't exist yet. Idempotent and
    # cheap; keeps the vector layer (loaded in app.core.state) untouched.
    init_db()


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(workspace_router)
app.include_router(document_router)
app.include_router(reading_router)
app.include_router(chat_router)
app.include_router(summary_router)
app.include_router(notes_router)
app.include_router(notes_tag_router)
app.include_router(flashcards_router)
app.include_router(citations_router)
app.include_router(analytics_router)
app.include_router(ingestion_router)
app.include_router(vision_router)
app.include_router(mmsearch_router)
app.include_router(mmcontext_router)
app.include_router(upload_router)
app.include_router(query_router)


@app.get("/")
def root():
    return {"message": "LexiMind backend is running"}
