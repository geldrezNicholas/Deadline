"""PDF to raw text, using pdfplumber."""

from __future__ import annotations

import pdfplumber


class PdfExtractionError(Exception):
    """The file couldn't be read as a PDF, or had no text in it."""


def extract_text(file_stream) -> str:
    """Pull all text out of a PDF file-like object.

    Pages are joined with blank lines. Raises PdfExtractionError for
    invalid PDFs and for scanned PDFs with no text layer.
    """
    try:
        with pdfplumber.open(file_stream) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:
        raise PdfExtractionError(f"Could not read PDF: {exc}") from exc

    text = "\n\n".join(pages).strip()

    if not text:
        # scanned PDFs with no text layer extract to an empty string
        raise PdfExtractionError(
            "No selectable text found. This looks like a scanned/image PDF; "
            "OCR would be required to read it."
        )

    return text
