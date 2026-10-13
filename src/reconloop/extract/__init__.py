"""Extractors turn trusted reports into Target rows. Pick per file type.

- csv_targets: targets already typed up (or exported by another tool). The demo uses this.
- pdf_text.extract: digital PDFs. Pulls text with pdfplumber and matches label patterns
  you configure. No OCR. Optional dependency: `pip install reconloop[pdf]`.
- pdf.extract_pdf: text-first extraction with per-tile OCR fallback, evidence and
  review diagnostics for rasterized dashboards. See docs/EXTRACTION.md.
"""
from .csv_targets import load_targets, write_targets
from .pdf import extract_pdf, ExtractionError, ExtractionResult

__all__ = ["load_targets", "write_targets", "extract_pdf", "ExtractionError", "ExtractionResult"]
