"""Media asset storage — the on-disk hierarchy for extracted temporal assets.

Thin wrapper over the Phase-4 `AssetStorage` (reused, not forked) so frames/subtitles/audio/
transcript land under the SAME per-workspace/per-document tree as document assets:

    assets/{workspace_id}/{document_id}/
        frames/{frame_id}.{ext}          (extracted representative frames + thumbnails)
        subtitles/{id}.vtt               (embedded/exported subtitle tracks)
        audio/{id}.wav                   (normalized audio track — future)
        transcript/{id}.json             (raw transcript dump — future)

Reusing `AssetStorage` keeps object-storage swap-out (S3/GCS) a single change for BOTH document and
media assets. `kind` is a free string on the underlying writer, so no new method is needed.
"""

from __future__ import annotations

from app.ingestion.storage import AssetStorage

# The kinds this module writes (documented for callers; AssetStorage itself is kind-agnostic).
FRAMES = "frames"
SUBTITLES = "subtitles"
AUDIO = "audio"
TRANSCRIPT = "transcript"


class MediaStorage(AssetStorage):
    """Same layout/behaviour as AssetStorage; a distinct type documents media-asset intent and
    gives us a place to add media-specific helpers (e.g. HLS segments) without touching documents."""

    def write_frame(self, workspace_id: str, document_id: str, frame_id: str,
                    data: bytes, ext: str = "jpg") -> str:
        return self.write_asset(workspace_id, document_id, FRAMES, frame_id, data, ext)

    def write_subtitle(self, workspace_id: str, document_id: str, subtitle_id: str,
                       data: bytes, ext: str = "vtt") -> str:
        return self.write_asset(workspace_id, document_id, SUBTITLES, subtitle_id, data, ext)
