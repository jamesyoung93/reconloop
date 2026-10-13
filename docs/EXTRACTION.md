# Extracting dashboard figures from PDFs

`extract_pdf` handles digital text, raster pages and PDFs mixing a digital header
with rasterized dashboard tiles. It extracts explicitly labelled numbers; it does
not infer figures from bar heights, chart lines, legends or unlabeled marks.

## Install and try it

```sh
python -m pip install -e ".[ocr,test-pdf]"
python examples/tableau_raster/generate_pdf.py
reconloop extract examples/tableau_raster/extract.toml --out out_extract
```

Install the **Tesseract executable** separately and put its folder on PATH;
`tesseract --version` should work. On Debian/Ubuntu use `sudo apt-get install
tesseract-ocr`. The Python extras install its wrapper and PDF/image libraries,
not the executable. Rendering uses pdfplumber/PDFium; Poppler is not required.
OCR runs locally, with no model endpoint.

The synthetic example has three KPIs on a hybrid page and a fully rasterized page.
Expected values: 1,250,000 / 2,400 / 0.125 on January 8, and 1,500,000 / 2,800 /
0.10 on January 15. This is a regression fixture, not an accuracy benchmark for
real Tableau exports.

The command saves `targets.csv`, `extraction.json` (raw figures, dates, confidence
and review issues), and `crops/` (regions actually sent to OCR). If a configured
figure is missing, ambiguous, invalid or below the confidence threshold, it exits
with **status 2** and excludes that figure from the CSV. The CSV may be partial:
resolve the issues before using it. Both `run_config` and `ReconSession.from_config`
refuse incomplete PDF sources rather than silently using the surviving subset.

## Configure the dashboard layout

Copy the example TOML to a private location with your PDF. Each pattern describes
one KPI on every selected page. Patterns apply to all pages by default; `pages`
selects explicit 1-based page numbers.

```toml
[[targets.sources]]
type = "pdf"
file = "dashboard.pdf"
report = "weekly_dashboard"
ocr = "auto"
dpi = 300
min_confidence = 0.8

[[targets.sources.patterns]]
metric = "net_sales"
label = 'Net Sales'
pages = [1]
bbox = [0.03, 0.30, 0.32, 0.72]
as_of = 'Week ending (\d{4}-\d{2}-\d{2})'
date_bbox = [0.0, 0.0, 1.0, 0.25]
unit = "currency"
split = "fit"
stated_rule = "Fiscal week, comparable stores, net sales."
```

`bbox` and `date_bbox` are `[left, top, right, bottom]` **page fractions** between
0 and 1, measured from the top-left. Crop each KPI to avoid neighboring tiles or
axis labels. The date can come from a separate header region; omit a region to
search the whole page. Use `as_of_value = "2026-01-08"` instead of `as_of` when
verified external metadata supplies the date. For non-ISO dates, use a matching
regex and `date_format = "%d/%m/%Y"` (for example).

The default matcher requires exactly one label followed immediately by a number,
including on the next line. For figures **above** their label, use a narrow tile
region and an explicit regex with a named `value` group:

```toml
label = 'Return Rate'
value_pattern = '(?P<value>\d+(?:\.\d+)?%)'
percent = "fraction"
unit = "fraction"
```

Multiple labels or matching figures require a narrower region or pattern. The
extractor does not pick an arbitrary first match or guess OCR digit corrections.

## Units and confidence

Numbers use English separators (`1,234.50`). Currency prefixes, accounting
negatives `(1,234)`, minus signs, K/M/B suffixes and percentages are supported.
`$1.25M` becomes `1250000`; `12.5%` becomes `0.125`. Use `percent = "points"` to
retain `12.5`, or `scale = 1000` for an unlabeled figure expressed in thousands.
Match the target unit to the SQL metric; reconciliation does not convert units.
Rounded dashboard labels need a suitable metric tolerance; OCR cannot recover
their hidden unrounded value.

`ocr = "auto"` tries text first, then OCR independently for a missing value or
date. `always` forces OCR; `never` uses text only. A digital page title does not
prevent OCR of raster KPI tiles. Source-level `lang`, `psm` and `timeout` control
Tesseract (defaults: `eng`, 6, 60 seconds per region). DPI is limited to 72-600;
rendered pages are limited to 50 megapixels.

OCR confidence is the minimum matched token confidence across label, value and
date, not a page average. Digital text receives 1.0 because no OCR was involved.
Neither score proves the pattern selected the intended figure: review the crops,
especially units, decimal separators, negative signs and dates.

## Python and reconciliation

```python
from reconloop.extract import extract_pdf, ExtractionError
try:
    result = extract_pdf("dashboard.pdf", "weekly_dashboard", patterns,
                         evidence_dir="private/crops")
except ExtractionError as exc:
    exc.result.write("private/extraction")
    raise
targets = result.targets
```

Add metric definitions and runner tables to the same TOML to reconcile PDF sources
directly with `reconloop run config.toml`. For audited runs, extract once, review
the evidence, then point `[targets] file` at the reviewed CSV. Multiple CSV/PDF
sources can be combined with repeated `[[targets.sources]]` entries. The original
`[targets] file = "targets.csv"` and legacy `pdf_text.extract` APIs still work.

Keep real PDFs, crops, diagnostics and business configs outside the public repo.
These files contain source figures, including holdouts.

## Limits

This is template-driven OCR, not automatic dashboard understanding. Tiny fonts,
overlapping labels, rotated tiles, international number formats and unlabeled
charts need layout-specific templates or another extractor. No real Tableau
export was used to establish accuracy; integration tests exercise actual local
Tesseract against known synthetic raster data.
