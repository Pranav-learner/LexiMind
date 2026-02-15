import pdfplumber
from typing import List, Dict
import re
from collections import Counter

def clean_extracted_text(pages: list) -> list:
    """
    Removes repeated headers, footers, URLs, and low-signal lines
    from extracted PDF pages.
    """

    #  Collect all lines across pages
    all_lines = []
    for page in pages:
        if isinstance(page["text"], list):
            all_lines.extend(page["text"])

    #  Find repeated lines (headers / footers)
    line_counts = Counter(
        line.strip() for line in all_lines if len(line.strip()) > 20
    )

    repeated_lines = {
        line for line, count in line_counts.items()
        if count > len(pages) * 0.5
    }

    cleaned_pages = []

    #  Clean each page
    for page in pages:
        cleaned_lines = []

        for line in page["text"]:
            line = line.strip()

            if line in repeated_lines:
                continue

            if re.search(r"https?://|www\.|@", line):
                continue

            if len(line) < 30:
                continue

            cleaned_lines.append(line)

        cleaned_pages.append({
            "page_number": page["page_number"],
            "text": cleaned_lines
        })

    return cleaned_pages



def extract_text_from_pdf(file_path: str) -> List[Dict]:
    extracted_pages = []

    with pdfplumber.open(file_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            # 🔑 convert text into list of lines
            lines = [
                line.strip()
                for line in text.split("\n")
                if line.strip()
            ]

            extracted_pages.append({
                "page_number": page_number,
                "text": lines
            })

    extracted_pages = clean_extracted_text(extracted_pages)

    return extracted_pages

