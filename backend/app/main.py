from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.query import router as query_router
from app.agents.api import router as agents_router
from app.agents.task_api import router as agent_tasks_router
from app.reasoning.api import router as verification_router
from app.orchestration.api import router as orchestration_router
from app.knowledge.api import router as knowledge_router
from app.memory.api import router as memory_router
from app.graphreason.api import router as graphreason_router
from app.knowledgeworkspace.api import router as knowledgeworkspace_router
from app.evaluation.api import router as evaluation_router
from app.observability.api import router as observability_router
from app.optimization.api import router as optimization_router
from app.learning.api import router as learning_router
from app.analytics.api import router as analytics_router
from app.api.upload import router as upload_router
from app.auth.api import router as auth_router
from app.chat.api import router as chat_router
from app.collaboration.api import router as collaboration_router
from app.citations.api import router as citations_router
from app.db.base import init_db
from app.documents.api import router as document_router
from app.documents.reading_api import router as reading_router
from app.flashcards.api import router as flashcards_router
from app.ingestion.api import router as ingestion_router
from app.media.api import router as media_router
from app.mediaworkspace.api import router as mediaworkspace_router
from app.mmcontext.api import router as mmcontext_router
from app.mmretrieval.api import router as mmsearch_router
from app.mmworkspace.api import router as mmworkspace_router
from app.vision.api import router as vision_router
from app.notes.api import router as notes_router
from app.notes.api import tag_router as notes_tag_router
from app.summaries.api import router as summary_router
from app.tintel.api import router as tintel_router
from app.tretrieval.api import router as tretrieval_router
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
app.include_router(collaboration_router)
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
app.include_router(media_router)
app.include_router(mediaworkspace_router)
app.include_router(agents_router)
app.include_router(agent_tasks_router)
app.include_router(verification_router)
app.include_router(orchestration_router)
app.include_router(knowledge_router)
app.include_router(memory_router)
app.include_router(graphreason_router)
app.include_router(knowledgeworkspace_router)
app.include_router(evaluation_router)
app.include_router(observability_router)
app.include_router(optimization_router)
app.include_router(learning_router)
app.include_router(tintel_router)
app.include_router(tretrieval_router)
app.include_router(vision_router)
app.include_router(mmsearch_router)
app.include_router(mmcontext_router)
app.include_router(mmworkspace_router)
app.include_router(upload_router)
app.include_router(query_router)


@app.get("/")
def root():
    return {"message": "LexiMind backend is running"}
