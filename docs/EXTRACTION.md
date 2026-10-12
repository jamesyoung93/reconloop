# Getting targets out of reports

Extraction is step one, and it's swappable. Whatever you use, the output is the same `targets.csv`.

| Source | Use | Notes |
|---|---|---|
| Digital PDF (exported, selectable text) | `reconloop.extract.pdf_text` (pdfplumber) or PyMuPDF | Uses the text layer; validate labels, dates and signs against the source. |
| Tables in digital PDFs | pdfplumber tables, camelot, tabula-py | Check merged cells and footnote markers |
| PowerPoint / Excel | python-pptx, openpyxl or pandas | Charts often have the data embedded; read it, don't screenshot it |
| Scanned PDF or image | Tesseract (pytesseract), PaddleOCR, docTR | Layout-aware OCR does better on tables |
| Messy tables and charts | A vision LLM with a fixed JSON schema | Ask for value, unit, period, label and page. Always validate the output |
| Whole-document layout | Docling, unstructured, marker | Good first pass for long mixed documents |
| Databricks built-ins | Document parsing and AI SQL functions, if your workspace has them enabled | Check availability in your workspace |

## Rules that save time

- **Prefer the text layer to OCR**, every time it exists.
- **Keep the page reference** for every figure, so the record can point back to it.
- **Capture the stated rule** from the report's footnotes or method notes, in its own words.
- **Set `confidence`** below 1 for OCR or model-extracted figures, and spot-check those first when a reconciliation fails.
- **Normalise units and periods** before writing targets: thousands vs units, week-ending vs week-starting dates.
