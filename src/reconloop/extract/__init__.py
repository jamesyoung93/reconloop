"""Extractors turn trusted reports into Target rows. Pick per file type.

- csv_targets: targets already typed up (or exported by another tool). The demo uses this.
- pdf_text.extract: digital PDFs. Pulls text with pdfplumber and matches label patterns
  you configure. Exact, no OCR. Optional dependency: `pip install reconloop[pdf]`.
- For scans, run OCR first (Tesseract, PaddleOCR, docTR) or a vision model with a fixed
  JSON schema, then feed the result through csv_targets. See docs/EXTRACTION.md.
"""
from .csv_targets import load_targets

__all__ = ["load_targets"]
