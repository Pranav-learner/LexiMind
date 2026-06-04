from typing import List, Dict
from app.services.embedding_service import generate_embedding
import numpy as np

MAX_WORDS = 250
SIM_THRESHOLD = 0.75


def cosine_similarity(vec1, vec2):
    vec1 = np.array(vec1)
    vec2 = np.array(vec2)
    return np.dot(vec1, vec2) / (
        np.linalg.norm(vec1) * np.linalg.norm(vec2)
    )


def chunk_text(pages: List[Dict]) -> List[Dict]:

    chunks = []
    chunk_index = 0

    for page in pages:
        page_number = page["page_number"]
        paragraphs = page["paragraphs"]

        current_chunk_text = []
        current_start_para = None
        previous_embedding = None
        current_section = None

        for para in paragraphs:

            # 🔹 Handle heading
            if para["is_heading"]:
                current_section = para["text"]
                continue  # do not embed heading itself

            paragraph_text = para["text"]
            paragraph_words = len(paragraph_text.split())

            paragraph_embedding = generate_embedding(paragraph_text)

            # 🔹 Start first chunk
            if current_start_para is None:
                current_chunk_text = [paragraph_text]
                current_start_para = para["paragraph_index"]
                previous_embedding = paragraph_embedding
                continue

            current_word_count = len(" ".join(current_chunk_text).split())

            similarity = cosine_similarity(
                previous_embedding,
                paragraph_embedding
            )

            # 🔥 Threshold logic
            if (
                current_word_count + paragraph_words > MAX_WORDS
                or similarity < SIM_THRESHOLD
            ):
                # Finalize chunk
                chunks.append({
                    "chunk_index": chunk_index,
                    "page_number": page_number,
                    "section_heading": current_section,
                    "start_paragraph": current_start_para,
                    "end_paragraph": para["paragraph_index"] - 1,
                    "text": " ".join(current_chunk_text)
                })

                chunk_index += 1

                # Start new chunk
                current_chunk_text = [paragraph_text]
                current_start_para = para["paragraph_index"]

            else:
                current_chunk_text.append(paragraph_text)

            previous_embedding = paragraph_embedding

        # 🔹 Finalize last chunk of page
        if current_chunk_text:
            chunks.append({
                "chunk_index": chunk_index,
                "page_number": page_number,
                "section_heading": current_section,
                "start_paragraph": current_start_para,
                "end_paragraph": paragraphs[-1]["paragraph_index"],
                "text": " ".join(current_chunk_text)
            })

            chunk_index += 1

    return chunks

## VERY iMPORATANT UPGRADATION
# For each page:

# Start a chunk

# Compare paragraph embedding to previous paragraph

# If similar → merge

# If topic shift → split

# If too long → split