import faiss
import os
import json
import numpy as np


class VectorStore:
    def __init__(
        self,
        dimension: int,
        index_path: str = "vector_index.faiss",
        metadata_path: str = "vector_metadata.json"
    ):
        self.dimension = dimension
        self.index_path = index_path
        self.metadata_path = metadata_path

        # Load existing index if present
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
            print(" Loaded FAISS index from disk")
        else:
            self.index = faiss.IndexFlatL2(dimension)
            print(" Created new FAISS index")

        # Load metadata if present
        if os.path.exists(self.metadata_path):
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)
            print(" Loaded metadata from disk")
        else:
            self.metadata = []

    def size(self) -> int:
        """Number of indexed vectors (== number of metadata records)."""
        return len(self.metadata)

    def add(self, embedding: list, metadata: dict):
        vector = np.array([embedding]).astype("float32")
        self.index.add(vector)
        self.metadata.append(metadata)

    def search(self, query_embedding: list, top_k: int = 3):
        vector = np.array([query_embedding]).astype("float32")

        distances, indices = self.index.search(vector, top_k)

        results = []

        for i, idx in enumerate(indices[0]):

            # FAISS pads results with -1 when top_k > number of indexed vectors. The
            # old check `idx < len(metadata)` let -1 through (since -1 < len), which
            # aliased to metadata[-1] and injected the last chunk repeatedly. Require a
            # valid, in-range index.
            if 0 <= idx < len(self.metadata):

                metadata_copy = self.metadata[idx].copy()

                distance = float(distances[0][i])

                # 🔥 Convert L2 distance to similarity score
                similarity = 1 / (1 + distance)

                metadata_copy["score"] = round(similarity, 4)

                results.append(metadata_copy)

        return results

    def save(self):
        faiss.write_index(self.index, self.index_path)

        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

        print(" Vector store saved to disk")

        