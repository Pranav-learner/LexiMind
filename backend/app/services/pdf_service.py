import pdfplumber
from typing import List, Dict
import re
from collections import Counter


def is_heading(text: str) -> bool:
    text = text.strip()

    words = text.split()
    word_count = len(words)

    if word_count > 15:
        return False

    if text.endswith("."):
        return False

    if re.match(r"^(\d+(\.\d+)*|Phase\s+\d+|Chapter\s+\d+)", text):
        return True

    if text.endswith(":"):
        return True

    capitalized_words = sum(1 for w in words if w[0].isupper())

    if word_count > 0 and capitalized_words / word_count > 0.6:
        return True

    if text.isupper():
        return True

    return False


def clean_extracted_text(pages: list) -> list:
    """
    Removes repeated headers/footers and junk paragraphs.
    Preserves headings.
    """

    all_paragraphs = []

    for page in pages:
        for para in page["paragraphs"]:
            if not para["is_heading"]:
                all_paragraphs.append(para["text"])

    paragraph_counts = Counter(
        p.strip() for p in all_paragraphs if len(p.strip()) > 20
    )

    repeated_paragraphs = {
        p for p, count in paragraph_counts.items()
        if count > len(pages) * 0.5
    }

    cleaned_pages = []


    for page in pages:
        cleaned_paragraphs = []

        for para in page["paragraphs"]:
            text = para["text"].strip()

            # Remove repeated non-heading paragraphs
            if not para["is_heading"] and text in repeated_paragraphs:
                continue

            # Remove URLs/emails
            if re.search(r"https?://|www\.|@", text):
                continue

            # Remove short junk paragraphs (but preserve headings)
            if not para["is_heading"] and len(text.split()) < 10:
                continue

            cleaned_paragraphs.append({
                "paragraph_index": para["paragraph_index"],
                "text": text,
                "is_heading": para["is_heading"]
            })

        if cleaned_paragraphs:
            cleaned_pages.append({
                "page_number": page["page_number"],
                "paragraphs": cleaned_paragraphs
            })

    return cleaned_pages




def extract_text_from_pdf(file_path: str) -> List[Dict]:
    """
    Extract text and structure into paragraphs with heading detection.
    """

    extracted_pages = []

    with pdfplumber.open(file_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):

            text = page.extract_text()
            if not text:
                continue

            text = text.replace("\r", "\n")

            lines = [line.strip() for line in text.split("\n")]

            paragraphs = []
            current_paragraph = []

            for line in lines:
                if not line:
                    if current_paragraph:
                        paragraph_text = " ".join(current_paragraph).strip()
                        paragraphs.append(paragraph_text)
                        current_paragraph = []
                else:
                    current_paragraph.append(line)

            if current_paragraph:
                paragraph_text = " ".join(current_paragraph).strip()
                paragraphs.append(paragraph_text)

            structured_paragraphs = []

            for idx, paragraph in enumerate(paragraphs):
                structured_paragraphs.append({
                    "paragraph_index": idx,
                    "text": paragraph,
                    "is_heading": is_heading(paragraph)
                })

            extracted_pages.append({
                "page_number": page_number,
                "paragraphs": structured_paragraphs
            })

    extracted_pages = clean_extracted_text(extracted_pages)

    return extracted_pages

