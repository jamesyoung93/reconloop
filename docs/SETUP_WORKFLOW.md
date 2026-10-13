# Report discovery and configuration drafts

The setup workflow separates three decisions: locating a reported figure, mapping
its meaning to source fields, and approving a metric definition. Its outputs are
review packages. Model output alone cannot approve a target or configuration.

## Locate figures across PDF pages

`extract_pdf_auto` scans selected pages through a caller-owned vision callback.
It needs metric/date requests, not table coordinates or label regexes. Each
request declares its unit and fit/holdout split before extraction.

```python
from reconloop.extract.automatic import extract_pdf_auto

requests = [
    {"metric": "sales", "label": "Net sales", "as_of": "2026-01-07", "unit": "currency", "split": "fit"},
    {"metric": "sales", "label": "Net sales", "as_of": "2026-01-14", "unit": "currency", "split": "holdout"},
]
result = extract_pdf_auto("private/report.pdf", "operations", requests,
    complete=complete_page, review=review_figure, pages=range(1, 49),
    max_pages=48, evidence_dir="private/extraction/crops", strict=False)
result.write("private/extraction")
```

`complete_page(png_bytes, prompt)` returns bounded JSON with a `cells` array. Each
cell has only `metric`, `as_of`, `text`, `bbox` and `quote`. `text` is the literal
displayed number; code parses signs, K/M/B and percentages. `bbox` uses normalized
page coordinates, and `quote` contains visible label/date context. The model
cannot choose the split or unit. Requests may explicitly specify `scale` and
`percent = "points"`; defaults are scale 1 and percentage fractions.

`review_figure(full_page_image, evidence)` must independently verify the source
figure, date, metric, unit, transcription and region, returning exactly `True`.
Without it, figures remain review issues. Repeated matches remain ambiguous even
when both were reviewed: narrow the page selection or use a precise extraction
template. Missing requests, malformed replies and failed pages leave the package
incomplete. `strict=True` raises `ExtractionError` carrying that review package.

Each page retains source/image hashes and optional evidence images. Successful
targets use `automatic_vision_reviewed`. Requests and replies are limited; the
default page budget is 100 and each render is limited to 50 megapixels. The
callback is responsible for endpoint credentials, request timeouts and cost
limits. Only connect an endpoint approved to receive these private pages.

This locates visible figures. It does not infer unreadable values or chart heights;
use the separate [calibrated bar workflow](EXTRACTION.md#calibrated-raster-bars)
when that measurement is appropriate. Tests use deterministic completion doubles
and synthetic PDFs; accuracy and cost on real reports need separate evaluation.

## Discover schema and dictionary mappings

```python
from reconloop.discovery import discover, write_draft

draft = discover(spark, "catalog.schema.facts", result.require_complete(),
    dictionary="private/data_dictionary.xlsx")
write_draft(draft, "private/setup-draft")
```

Discovery reads Spark schema metadata without scanning fact rows. Offline callers
can pass `spark=None` and `columns=[{"name": "sales", "data_type": "double"}, ...]`.
CSV dictionaries work without extra dependencies. Install `reconloop[discovery]`
for XLSX. Dictionary headers are `table`, `column`, `description`, `unit`, and
`data_type`; only the first two are required. `dictionary_columns` maps those
canonical names to other headers, and `sheet` selects an Excel worksheet.
Rows are streamed, filtered to the exact fully qualified table, and bounded at
200,000 rows by default. Conflicting column descriptions and formulas in matching
rows fail explicitly. No workbook formulas or macros are executed.

Candidates are ranked using names, definitions and units. Ambiguous dates remain
unselected. Optional `complete(prompt)` may choose a column, date column and
sum/avg/count aggregation from the proposed candidates. Arbitrary SQL, unknown
fields and model approval flags are rejected. The prompt contains bounded
metadata rather than source samples or target values.

```sh
reconloop discover private/schema.json private/targets.csv --table catalog.schema.facts --dictionary private/dictionary.csv --out private/setup-draft
```

The new output directory contains `draft.json`, `targets.csv` and `config.toml`.
Review the mapping rationale and questions, verify aggregation/units, and add the
correct time window, population, grain, vintage and quality checks. The initial
SQL uses a single calendar day and one candidate measure; it does not invent
business alternatives or claim a daily sum is the correct definition. Missing
mappings use a NULL placeholder that cannot pass scalar-result validation.

The config includes `[draft] status = "needs_review"`. `load_config`, sessions,
batch runs and jobs refuse it. After independent review and necessary edits,
change the status to `approved`. This explicit convention is an execution gate,
not an identity-based approval system. Generated SQL/configuration is trusted
executable material after approval, like any other reconloop configuration.
