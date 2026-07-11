"""The vision engine — the ONLY bridge from a vision job to the heavy vision-language libraries.

Like every AI engine in LexiMind, this is INJECTED and imports heavy libs (CLIP/SigLIP/BLIP/torch)
LAZILY, so `app.vision.*` imports with none of them and tests substitute `FakeVisionEngine`.

`process(job, assets, storage)` is a generator of events the SERVICE consumes + persists:

    {"type": "stage",    "stage": str, "progress": int}
    {"type": "analysis", "asset_type", "asset_id", "page_number", "image_type", "caption",
                         "objects", "relationships", "structured", "keywords", "topics",
                         "complexity", "confidence", "language", "thumbnail": bytes|None}
    {"type": "embedding","asset_type", "asset_id", "vector", "model", "model_family", "dim"}
    {"type": "final",    "model_name", "embedding_model", "pipeline_version"}

`assets` is the list of Module-1 extracted assets (image/figure/table) to understand. The vision
EMBEDDER is a separate swappable abstraction (`VisionEmbedder`) so the model can change without
touching consumers (Step 10).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterator, List, Protocol, Tuple

from app.vision import analyzers
from app.vision.models import VISION_PIPELINE_VERSION


# ====================================================================== embedder abstraction
class VisionEmbedder(Protocol):
    family: str
    model: str
    dim: int
    def embed(self, image_bytes: bytes, caption: str) -> Tuple[List[float], str, str, int]: ...


class FakeVisionEmbedder:
    """Deterministic embedder for tests/contract — a stable pseudo-vector from the caption hash."""

    family = "fake"
    model = "fake-clip-vit"
    dim = 16

    def embed(self, image_bytes: bytes, caption: str) -> Tuple[List[float], str, str, int]:
        seed = hashlib.sha256((caption or "").encode("utf-8")).digest()
        vec = [(seed[i % len(seed)] / 255.0) for i in range(self.dim)]
        return vec, self.model, self.family, self.dim


class ClipVisionEmbedder:
    """Production CLIP/SigLIP embedder (lazy). Swappable behind the same interface."""

    family = "clip"
    model = "ViT-B-32"
    dim = 512

    def embed(self, image_bytes: bytes, caption: str) -> Tuple[List[float], str, str, int]:  # pragma: no cover
        import io
        import open_clip
        import torch
        from PIL import Image
        model, _, preprocess = _clip_singleton()
        image = preprocess(Image.open(io.BytesIO(image_bytes)).convert("RGB")).unsqueeze(0)
        with torch.no_grad():
            feats = model.encode_image(image)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        vec = feats[0].tolist()
        return vec, self.model, self.family, len(vec)


_CLIP = None


def _clip_singleton():  # pragma: no cover - production only
    global _CLIP
    if _CLIP is None:
        import open_clip
        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
        model.eval()
        _CLIP = (model, None, preprocess)
    return _CLIP


class VisionEngine(Protocol):
    def process(self, job, assets: List[Dict[str, Any]], storage) -> Iterator[Dict[str, Any]]: ...


# ====================================================================== fake (tests + contract)
class FakeVisionEngine:
    """Deterministic engine: classifies each asset, builds structured understanding + a semantic
    caption via the pure analyzers, emits a thumbnail + a (fake) embedding, then a final. Mirrors the
    production event contract with no CLIP/BLIP."""

    def __init__(self, embedder: VisionEmbedder | None = None):
        self.embedder = embedder or FakeVisionEmbedder()

    def process(self, job, assets, storage) -> Iterator[Dict[str, Any]]:
        yield {"type": "stage", "stage": "analyzing", "progress": 10}
        total = max(1, len(assets))
        for i, asset in enumerate(assets, start=1):
            image_type, conf = analyzers.classify_asset(asset)
            structured = analyzers.build_structured(asset, image_type)
            caption = analyzers.build_caption(image_type, structured, asset.get("page_number", 0))
            keywords, topics = analyzers.keywords_and_topics(image_type, structured, caption)
            complexity = analyzers.complexity_of(structured)
            objects = structured.get("nodes") or structured.get("columns") or structured.get("components") or []
            relationships = structured.get("edges") or structured.get("relationships") or []

            yield {"type": "analysis", "asset_type": asset["asset_type"], "asset_id": asset["asset_id"],
                   "page_number": asset.get("page_number", 0), "image_type": image_type, "caption": caption,
                   "objects": objects, "relationships": relationships, "structured": structured,
                   "keywords": keywords, "topics": topics, "complexity": complexity,
                   "confidence": conf, "language": "en", "thumbnail": b"\x89PNGthumb"}

            vec, model, family, dim = self.embedder.embed(b"", caption)
            yield {"type": "embedding", "asset_type": asset["asset_type"], "asset_id": asset["asset_id"],
                   "vector": vec, "model": model, "model_family": family, "dim": dim}

            yield {"type": "stage", "stage": "analyzing", "progress": min(95, int(i / total * 90) + 10)}

        yield {"type": "final", "model_name": "fake-vlm", "embedding_model": self.embedder.model,
               "pipeline_version": VISION_PIPELINE_VERSION}


# ====================================================================== production (lazy heavy libs)
class PipelineVisionEngine:
    """Production engine: a vision-language model for captioning + classification and a CLIP/SigLIP
    embedder for vision vectors. All heavy imports are LAZY and failures degrade gracefully to the
    pure analyzers (so a diagram still gets structured metadata + a caption even without a VLM)."""

    def __init__(self, embedder: VisionEmbedder | None = None):
        self.embedder = embedder or ClipVisionEmbedder()

    def process(self, job, assets, storage) -> Iterator[Dict[str, Any]]:  # pragma: no cover - production only
        yield {"type": "stage", "stage": "analyzing", "progress": 5}
        total = max(1, len(assets))
        for i, asset in enumerate(assets, start=1):
            data = self._read(asset.get("storage_path", ""))
            # Classification + caption: try a VLM, else fall back to the pure analyzers.
            image_type, conf = self._classify(data, asset)
            structured = analyzers.build_structured(asset, image_type)
            caption = self._caption(data) or analyzers.build_caption(image_type, structured, asset.get("page_number", 0))
            keywords, topics = analyzers.keywords_and_topics(image_type, structured, caption)
            yield {"type": "analysis", "asset_type": asset["asset_type"], "asset_id": asset["asset_id"],
                   "page_number": asset.get("page_number", 0), "image_type": image_type, "caption": caption,
                   "objects": structured.get("nodes") or structured.get("columns") or [],
                   "relationships": structured.get("edges") or structured.get("relationships") or [],
                   "structured": structured, "keywords": keywords, "topics": topics,
                   "complexity": analyzers.complexity_of(structured), "confidence": conf,
                   "language": "en", "thumbnail": self._thumbnail(data)}
            try:
                vec, model, family, dim = self.embedder.embed(data, caption)
                yield {"type": "embedding", "asset_type": asset["asset_type"], "asset_id": asset["asset_id"],
                       "vector": vec, "model": model, "model_family": family, "dim": dim}
            except Exception:
                pass
            yield {"type": "stage", "stage": "analyzing", "progress": min(95, int(i / total * 90) + 5)}
        yield {"type": "final", "model_name": "blip2", "embedding_model": self.embedder.model,
               "pipeline_version": VISION_PIPELINE_VERSION}

    def _read(self, path: str) -> bytes:  # pragma: no cover
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except Exception:
            return b""

    def _classify(self, data: bytes, asset) -> Tuple[str, float]:  # pragma: no cover
        # A real classifier (CLIP zero-shot over the taxonomy) refines this; fall back to hints.
        return analyzers.classify_asset(asset)

    def _caption(self, data: bytes):  # pragma: no cover
        try:
            from transformers import BlipForConditionalGeneration, BlipProcessor  # noqa
            import io
            from PIL import Image
            proc, model = _blip_singleton()
            inputs = proc(Image.open(io.BytesIO(data)).convert("RGB"), return_tensors="pt")
            out = model.generate(**inputs, max_new_tokens=40)
            return proc.decode(out[0], skip_special_tokens=True)
        except Exception:
            return None

    def _thumbnail(self, data: bytes):  # pragma: no cover
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((256, 256))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None


_BLIP = None


def _blip_singleton():  # pragma: no cover - production only
    global _BLIP
    if _BLIP is None:
        from transformers import BlipForConditionalGeneration, BlipProcessor
        proc = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
        _BLIP = (proc, model)
    return _BLIP
