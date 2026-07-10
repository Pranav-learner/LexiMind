"""Workspace domain module (Phase 3, Module 1).

An isolated knowledge environment that every future artifact (documents, chats, notes,
flashcards, summaries) belongs to. Layered with clean separation:

    models.py       ORM entity + denormalized counters
    schemas.py      Pydantic DTOs + list query enums
    validation.py   pure field validation/normalization
    errors.py       transport-agnostic domain errors
    repository.py   all SQL (owner-scoped, soft-delete aware)
    service.py      business rules (CRUD, dup-name, archive/restore, counters)
    api.py          thin authenticated HTTP routes

Business logic never lives in the API handlers; the API never issues SQL directly.
"""
