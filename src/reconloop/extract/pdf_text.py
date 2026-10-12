"""Digital-PDF extraction with page references. No OCR: reads the text layer.

Configure one pattern per figure you want, for example:

    patterns = [
        {"metric": "weekly_sales", "label": r"Weekly sales", "as_of": r"Week ending (\\d{4}-\\d{2}-\\d{2})"},
    ]

For each page, the first number after `label` becomes the value; `as_of` is read from
the same page. Every target keeps its file and page so the record can point back to it.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..schema import Target

NUM = r"(?P<value>[-+]?\d[\d,]*\.?\d*)"


def extract(pdf_path: str | Path, report: str, patterns: list[dict], split: str = "fit") -> list[Target]:
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover
        raise ImportError("pip install pdfplumber (or reconloop[pdf])") from e
    out: list[Target] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for pat in patterns:
                m = re.search(pat["label"] + r"[^\d+\-\n]{0,40}?" + NUM, text)
                d = re.search(pat["as_of"], text) if pat.get("as_of") else None
                if not m:
                    continue
                out.append(Target(target_id=f"{report}-{pat['metric']}-p{pno}", report=report, metric=pat["metric"],
                                  as_of=d.group(1) if d else "", value=float(m.group("value").replace(",", "")),
                                  stated_rule=pat.get("stated_rule", ""), source_file=Path(pdf_path).name,
                                  page=str(pno), split=split, confidence=0.95))
    return out
