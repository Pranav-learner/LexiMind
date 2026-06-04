"""One-off migration: backfill Phase-1 metadata onto the existing FAISS metadata.

The index built before Phase 1 has 2,436 records with only:
    chunk_index, end_paragraph, page_number, section_heading, source,
    start_paragraph, text

This script adds the enriched fields WITHOUT re-embedding or touching the FAISS vectors
(only vector_metadata.json changes, and only by adding keys):
    chunk_id, document_id, filename, section, topic, created_at

It is:
- idempotent: re-running it does not change already-migrated records;
- non-destructive: writes a timestamped .bak backup before saving.

Run from backend/:   python -m scripts.migrate_metadata
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone

from app.core.config import settings
from app.retrieval.schemas import derive_chunk_id, derive_document_id


def migrate() -> None:
    path = settings.metadata_path
    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)

    backup = f"{path}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bak"
    shutil.copy2(path, backup)
    print(f"Backup written: {backup}")

    migrated_at = datetime.now(timezone.utc).isoformat()
    changed = 0

    for rec in records:
        source = rec.get("source", "unknown")
        before = dict(rec)

        rec.setdefault("filename", source)
        rec.setdefault("document_id", derive_document_id(source))
        if not rec.get("chunk_id"):
            rec["chunk_id"] = derive_chunk_id(source, rec.get("chunk_index"))
        section = rec.get("section") or rec.get("section_heading")
        rec.setdefault("section", section)
        rec.setdefault("topic", section)
        # created_at marks when the record was *migrated*; original ingest time is unknown.
        rec.setdefault("created_at", migrated_at)

        if rec != before:
            changed += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Migrated {changed}/{len(records)} records -> {path}")


if __name__ == "__main__":
    migrate()
