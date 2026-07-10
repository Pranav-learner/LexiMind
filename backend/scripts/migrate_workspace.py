"""One-off migration: put every existing chunk into a 'Default' workspace (Phase 3).

Before Phase 3, chunks had no workspace binding. Once retrieval starts filtering by
`workspace_id`, those legacy chunks would vanish from any workspace-scoped query. This
script prevents that by:

1. ensuring a 'Default' workspace row exists (owned by --owner-id, default "local"), and
2. backfilling `workspace_id` onto every metadata record that lacks one.

It mirrors scripts/migrate_metadata.py:
- idempotent: re-running does not change already-tagged records;
- non-destructive: writes a timestamped .bak backup of vector_metadata.json before saving;
- FAISS vectors are never touched (only the JSON sidecar gains a key).

The workspace's document_count is set to the number of distinct documents backfilled.

Run from backend/:   python -m scripts.migrate_workspace  [--owner-id <id>]  [--name Default]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone

from app.core.config import settings
from app.db.base import SessionLocal, init_db
from app.workspaces.errors import DuplicateWorkspaceName
from app.workspaces.repository import WorkspaceRepository
from app.workspaces.service import WorkspaceService


def _ensure_default_workspace(owner_id: str, name: str) -> str:
    """Return the id of the owner's workspace called `name`, creating it if needed."""
    init_db()
    db = SessionLocal()
    try:
        repo = WorkspaceRepository(db)
        service = WorkspaceService(repo)
        # Look for an existing live workspace with that name (case-insensitive) for the owner.
        items, _ = repo.list(owner_id, page=1, page_size=100)
        for ws in items:
            if ws.name.casefold() == name.casefold():
                return ws.id
        try:
            ws = service.create(
                owner_id,
                name=name,
                description="Auto-created during the Phase 3 workspace migration; holds all "
                "documents indexed before workspaces existed.",
                icon="🗂️",
                color="#64748b",
            )
            return ws.id
        except DuplicateWorkspaceName:
            items, _ = repo.list(owner_id, page=1, page_size=100)
            return next(w.id for w in items if w.name.casefold() == name.casefold())
    finally:
        db.close()


def _set_document_count(owner_id: str, workspace_id: str, count: int) -> None:
    db = SessionLocal()
    try:
        repo = WorkspaceRepository(db)
        ws = repo.get(workspace_id, owner_id)
        if ws is not None:
            ws.document_count = count
            repo.save(ws)
    finally:
        db.close()


def migrate(owner_id: str, name: str) -> None:
    workspace_id = _ensure_default_workspace(owner_id, name)
    print(f"Default workspace: {workspace_id} (owner={owner_id!r}, name={name!r})")

    path = settings.metadata_path
    if not os.path.exists(path):
        print(f"No metadata file at {path}; nothing to backfill.")
        return

    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)

    backup = f"{path}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bak"
    shutil.copy2(path, backup)
    print(f"Backup written: {backup}")

    changed = 0
    docs: set[str] = set()
    for rec in records:
        if not rec.get("workspace_id"):
            rec["workspace_id"] = workspace_id
            changed += 1
        if rec.get("workspace_id") == workspace_id:
            docs.add(rec.get("document_id") or rec.get("source") or rec.get("chunk_id"))

    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    _set_document_count(owner_id, workspace_id, len(docs))
    print(f"Backfilled {changed}/{len(records)} records -> {path}")
    print(f"Set document_count={len(docs)} on the Default workspace.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill legacy chunks into a Default workspace.")
    parser.add_argument(
        "--owner-id",
        default=os.environ.get("LEXIMIND_MIGRATE_OWNER", "local"),
        help="User id to own the Default workspace (default: 'local' or $LEXIMIND_MIGRATE_OWNER).",
    )
    parser.add_argument("--name", default="Default", help="Workspace name (default: 'Default').")
    args = parser.parse_args()
    migrate(args.owner_id, args.name)
