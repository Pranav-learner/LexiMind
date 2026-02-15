from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.health import router as health_router
from app.api.upload import router as upload_router
from app.api.query import router as query_router


app = FastAPI(title="LexiMind API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(upload_router)
app.include_router(query_router)


@app.get("/")
def root():
    return {"message": "LexiMind backend is running"}



