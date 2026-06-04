# This library converts text into semantic vectors locally(no API calls)
from typing import List

from sentence_transformers import SentenceTransformer

from app.core.config import settings

# Load a pre-trained embedding model (name/dim centralized in config).
# Default all-MiniLM-L6-v2 is small, fast, and outputs 384-dim vectors.
model = SentenceTransformer(settings.embedding_model)

def generate_embedding(text:str) -> list:
    """
    Convert a piece of text into a semantic embedding.

    WHY this function exists:
    - Single responsibility: text → vector
    - Reusable for both document chunks and user queries
    """
    # Encode the text into a numerical vector
    # The model understands semantic meaning, not just keywords
    embedding = model.encode(text)

    # Convert NumPy array to Python list
    # This makes it easier to store and pass around
    return embedding.tolist()


def generate_embeddings(texts: List[str]) -> List[list]:
    """Batch-encode many texts in one model call.

    WHY: encoding chunks one-at-a-time (the current ingestion loop) pays Python/torch
    overhead per item. Batching is materially faster for multi-chunk documents and is
    used by the evaluation harness and the (refactored) ingestion path.
    """
    if not texts:
        return []
    vectors = model.encode(texts)
    return [v.tolist() for v in vectors]

