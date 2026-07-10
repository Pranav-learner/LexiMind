"""Document domain module (Phase 3, Module 2).

A Document is a first-class knowledge asset inside a workspace — the durable, structured
identity for an uploaded file (its lifecycle, statistics, and link to the vector layer).
Layered with the same clean separation as the workspaces module:

    models.py       ORM entity (status, statistics, vector link) + indexes
    schemas.py      Pydantic DTOs + list query enums + status vocabularies
    validation.py   pure field/file validation + language/word helpers
    errors.py       transport-agnostic domain errors
    repository.py   all SQL (owner + workspace scoped, soft-delete aware)
    service.py      lifecycle rules (upload/process/rename/archive/delete, counters)
    indexing.py     the ONLY bridge to FAISS/BM25 (count/remove/health), faiss injected
    api.py          thin authenticated HTTP routes under /workspaces/{id}/documents

Business logic never lives in the API handlers; the API never issues SQL directly; the
documents package never imports faiss (the vector singletons are injected).
"""
