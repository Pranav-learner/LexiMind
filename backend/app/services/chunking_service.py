from typing import List,Dict

def chunk_text(
    pages: list,
    max_words: int = 250,
    min_words: int = 80
) -> list:

    chunks = []

    for page in pages:
        # FIRST: extract text from page
        text = page["text"]

        #  SECOND: normalize text to string
        if isinstance(text, list):
            text = "\n".join(text)

        page_number = page["page_number"]

        #  THIRD: split into paragraphs
        paragraphs = [
            p.strip()
            for p in text.split("\n\n")
            if len(p.strip()) > 40
        ]

        current_chunk = []
        current_word_count = 0
        chunk_index = 0

        for paragraph in paragraphs:
            word_count = len(paragraph.split())

            if current_word_count + word_count > max_words:
                if current_word_count >= min_words:
                    chunks.append({
                        "page_number": page_number,
                        "chunk_index": chunk_index,
                        "text": " ".join(current_chunk)
                    })
                    chunk_index += 1

                current_chunk = []
                current_word_count = 0

            current_chunk.append(paragraph)
            current_word_count += word_count

        if current_word_count >= min_words:
            chunks.append({
                "page_number": page_number,
                "chunk_index": chunk_index,
                "text": " ".join(current_chunk)
            })

        print(f"Page {page_number}: {len(paragraphs)} paragraphs found")
    

    return chunks
