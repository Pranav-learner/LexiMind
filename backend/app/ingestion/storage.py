"""Asset storage — the on-disk hierarchy for extracted multimodal assets.

Layout (per the module spec), rooted under the configured assets dir:

    assets/{workspace_id}/{document_id}/
        images/{image_id}.{ext}
        figures/{figure_id}.{ext}
        tables/{table_id}.json      (future: CSV export)
        ocr/{page}.txt              (future: raw OCR dump)

Kept deliberately simple (local filesystem) so it's easy to swap for object storage (S3/GCS) later
behind the same `AssetStorage` interface. Writes are incremental (one file per asset) and idempotent
by asset id.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.config import settings


class AssetStorage:
    def __init__(self, root: str | None = None):
        # Default: a sibling of the upload dir, so tests (which point uploads at a temp dir) also
        # keep extracted assets in the throwaway location.
        base = root or os.path.join(os.path.dirname(settings.upload_dir), "assets")
        self.root = Path(base)

    def _dir(self, workspace_id: str, document_id: str, kind: str) -> Path:
        d = self.root / workspace_id / document_id / kind
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_asset(self, workspace_id: str, document_id: str, kind: str, asset_id: str,
                    data: bytes, ext: str = "png") -> str:
        """Write an asset's bytes and return its storage path. `kind` ∈ images|figures|tables|ocr."""
        path = self._dir(workspace_id, document_id, kind) / f"{asset_id}.{ext}"
        path.write_bytes(data or b"")
        return str(path)

    def exists(self, path: str) -> bool:
        return bool(path) and Path(path).exists()

    def remove_document(self, workspace_id: str, document_id: str) -> None:
        import shutil
        d = self.root / workspace_id / document_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
