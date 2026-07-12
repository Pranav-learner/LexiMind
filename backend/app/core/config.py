"""Central configuration for LexiMind.

WHY this exists:
- Previously paths and model names were string literals scattered across modules
  (vector_store.py, embedding_service.py, answer_service.py). That made the system
  hard to test (no way to point at a temp index) and hard to tune.
- This module is the single source of truth for paths, model names, and retrieval
  parameters. Everything is overridable via environment variables so the same code
  runs in dev, tests, and (future) deployment without edits.

Offline-first: every default points at a local file or a locally-cached model. No
value here implies a network call at request time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# backend/ directory (this file is backend/app/core/config.py -> parents[2] == backend/)
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # --- Storage paths (resolved relative to backend/ unless absolute) ---
    index_path: str = field(
        default_factory=lambda: str(BACKEND_DIR / _env("LEXIMIND_INDEX_PATH", "vector_index.faiss"))
    )
    metadata_path: str = field(
        default_factory=lambda: str(BACKEND_DIR / _env("LEXIMIND_METADATA_PATH", "vector_metadata.json"))
    )
    upload_dir: str = field(
        default_factory=lambda: str(BACKEND_DIR / _env("LEXIMIND_UPLOAD_DIR", "uploaded_pdfs"))
    )

    # --- Models ---
    embedding_model: str = field(default_factory=lambda: _env("LEXIMIND_EMBED_MODEL", "all-MiniLM-L6-v2"))
    embedding_dim: int = field(default_factory=lambda: _env_int("LEXIMIND_EMBED_DIM", 384))
    reranker_model: str = field(default_factory=lambda: _env("LEXIMIND_RERANKER_MODEL", "BAAI/bge-reranker-base"))
    llm_model: str = field(default_factory=lambda: _env("LEXIMIND_LLM_MODEL", "llama3"))

    # --- Retrieval parameters (the Phase-1 pipeline knobs) ---
    dense_top_k: int = field(default_factory=lambda: _env_int("LEXIMIND_DENSE_TOP_K", 30))
    sparse_top_k: int = field(default_factory=lambda: _env_int("LEXIMIND_SPARSE_TOP_K", 30))
    rrf_k: int = field(default_factory=lambda: _env_int("LEXIMIND_RRF_K", 60))
    rerank_candidates: int = field(default_factory=lambda: _env_int("LEXIMIND_RERANK_CANDIDATES", 30))
    final_top_k: int = field(default_factory=lambda: _env_int("LEXIMIND_FINAL_TOP_K", 5))

    # Toggle reranking off (e.g. in CI where the model isn't cached) without code changes.
    enable_reranker: bool = field(default_factory=lambda: _env("LEXIMIND_ENABLE_RERANKER", "1") != "0")

    # --- Phase 2: context engineering ---
    # Model context window and the reserves carved out of it before chunks get any budget.
    context_window: int = field(default_factory=lambda: _env_int("LEXIMIND_CONTEXT_WINDOW", 8192))
    system_prompt_reserve: int = field(default_factory=lambda: _env_int("LEXIMIND_SYSTEM_RESERVE", 500))
    response_reserve: int = field(default_factory=lambda: _env_int("LEXIMIND_RESPONSE_RESERVE", 1000))
    # Near-duplicate Jaccard threshold (>= this similarity => treated as a duplicate).
    dedup_threshold: float = field(default_factory=lambda: _env_float("LEXIMIND_DEDUP_THRESHOLD", 0.85))
    # Enable extractive compression to fit more evidence inside the budget.
    enable_compression: bool = field(default_factory=lambda: _env("LEXIMIND_ENABLE_COMPRESSION", "1") != "0")

    # --- Phase 3 Module 1: workspaces + minimal auth ---
    # SQLite is the project's first relational store. It holds structured domain rows
    # (users, workspaces) that do NOT belong in the FAISS/JSON vector layer. Kept as a
    # single embedded file so the system stays offline-first and zero-ops in dev.
    database_url: str = field(
        default_factory=lambda: _env(
            "LEXIMIND_DATABASE_URL",
            f"sqlite:///{BACKEND_DIR / 'leximind.db'}",
        )
    )
    # Secret used to sign auth tokens (HMAC). MUST be overridden in production via env.
    secret_key: str = field(default_factory=lambda: _env("LEXIMIND_SECRET_KEY", "dev-insecure-change-me"))
    # Auth token lifetime (seconds). Default 7 days.
    token_ttl_seconds: int = field(default_factory=lambda: _env_int("LEXIMIND_TOKEN_TTL", 7 * 24 * 3600))
    # PBKDF2 iteration count for password hashing (stdlib hashlib, no external dep).
    pbkdf2_iterations: int = field(default_factory=lambda: _env_int("LEXIMIND_PBKDF2_ITERS", 240_000))

    # --- Phase 3 Module 2: Document Library ---
    # Maximum accepted upload size (bytes). Default 50 MB. Enforced in the documents service
    # BEFORE any extraction/embedding work so oversized files are rejected cheaply.
    max_upload_bytes: int = field(default_factory=lambda: _env_int("LEXIMIND_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
    # Currently supported document extensions. Kept as a set so future media types (images,
    # audio, video, web pages) slot in without code changes beyond an extractor.
    supported_document_extensions: frozenset = field(
        default_factory=lambda: frozenset(
            e.strip().lower()
            for e in _env("LEXIMIND_SUPPORTED_DOC_EXTS", "pdf").split(",")
            if e.strip()
        )
    )

    # --- Phase 3 Module 4: Persistent AI Chat Workspace ---
    # Token-aware conversation memory: how much of the prior conversation to feed the LLM. Kept
    # well under the context window so retrieved context + the answer always fit.
    chat_history_token_budget: int = field(default_factory=lambda: _env_int("LEXIMIND_CHAT_HISTORY_TOKENS", 1500))
    chat_history_max_messages: int = field(default_factory=lambda: _env_int("LEXIMIND_CHAT_HISTORY_MAX_MSGS", 20))

    # --- Phase 5 Module 1: Audio & Video Processing Engine ---
    # Media files are large; a separate, higher ceiling than document uploads (default 2 GB). The
    # media upload path enforces this BEFORE any transcription work so oversized files fail cheaply.
    max_media_bytes: int = field(default_factory=lambda: _env_int("LEXIMIND_MAX_MEDIA_BYTES", 2 * 1024 * 1024 * 1024))
    # Guard against corrupt-metadata durations (default 6 hours). 0/unknown is allowed.
    max_media_duration_ms: int = field(default_factory=lambda: _env_int("LEXIMIND_MAX_MEDIA_DURATION_MS", 6 * 3600 * 1000))
    # Whisper model size + video sampling knobs (used by PipelineMediaEngine; overridable per-deploy).
    whisper_model: str = field(default_factory=lambda: _env("LEXIMIND_WHISPER_MODEL", "base"))
    frame_interval_ms: int = field(default_factory=lambda: _env_int("LEXIMIND_FRAME_INTERVAL_MS", 5000))
    scene_threshold: float = field(default_factory=lambda: _env_float("LEXIMIND_SCENE_THRESHOLD", 27.0))
    max_frames_per_media: int = field(default_factory=lambda: _env_int("LEXIMIND_MAX_FRAMES", 400))


settings = Settings()
