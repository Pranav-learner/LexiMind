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

    def count_where(self, predicate) -> int:
        """Number of chunk records whose metadata satisfies `predicate(meta) -> bool`.

        Used by the Document Library to report a document's live chunk/embedding count
        without loading FAISS vectors.
        """
        return sum(1 for meta in self.metadata if predicate(meta))

    def remove_where(self, predicate) -> int:
        """Delete every chunk whose metadata satisfies `predicate` and rebuild the index.

        FAISS's IndexFlatL2 has no cheap per-id delete, and the metadata list is positional,
        so the safe operation is a rebuild: reconstruct the vectors we keep and re-add them to
        a fresh index. Returns the number of chunks removed. Caller is responsible for
        persisting (`save()`) and marking any dependent sparse index dirty.

        Kept here so all FAISS access stays in this module; the documents layer never imports
        faiss.
        """
        keep_positions = [i for i, meta in enumerate(self.metadata) if not predicate(meta)]
        removed = len(self.metadata) - len(keep_positions)
        if removed == 0:
            return 0

        new_index = faiss.IndexFlatL2(self.dimension)
        if keep_positions:
            # reconstruct_n needs a contiguous range; reconstruct kept vectors individually
            # (correct regardless of gaps) and re-add them in one batch.
            vectors = np.vstack(
                [self.index.reconstruct(int(i)) for i in keep_positions]
            ).astype("float32")
            new_index.add(vectors)

        self.index = new_index
        self.metadata = [self.metadata[i] for i in keep_positions]
        return removed

    def save(self):
        faiss.write_index(self.index, self.index_path)

        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

        print(" Vector store saved to disk")

