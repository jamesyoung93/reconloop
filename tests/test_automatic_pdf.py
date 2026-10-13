import json

import pytest

from reconloop.extract.automatic import extract_pdf_auto


@pytest.fixture
def pdf(tmp_path):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    pytest.importorskip("pdfplumber")
    path = tmp_path / "operations.pdf"
    c = canvas.Canvas(str(path))
    for text in ("Operations 2026-01-01 Sales 1.2K", "Operations 2026-01-02 Sales 1.5K"):
        c.drawString(50, 700, text)
        c.showPage()
    c.save()
    return path


def requests():
    return [dict(metric="sales", as_of=f"2026-01-0{i}", unit="currency", split="holdout" if i == 2 else "fit") for i in (1, 2)]


def cell(day=1):
    return dict(metric="sales", as_of=f"2026-01-0{day}", text="1.2K" if day == 1 else "1.5K",
                bbox=[.05, .05, .8, .3], quote="Operations Sales")


def completion():
    pages = iter([cell(1), cell(2)])
    def complete(png, prompt):
        assert png.startswith(b"\x89PNG") and "untrusted" in prompt and "holdout" not in prompt
        return json.dumps({"cells": [next(pages)]})
    return complete


def test_auto_discovery_requires_review_and_preserves_declared_splits(pdf, tmp_path):
    result = extract_pdf_auto(pdf, "operations", requests(), complete=completion(), strict=False)
    assert not result.targets and len(result.issues) == 2
    result = extract_pdf_auto(pdf, "operations", requests(), complete=completion(), review=lambda im, evidence: True,
                              evidence_dir=tmp_path / "crops")
    assert [t.value for t in result.targets] == [1200, 1500]
    assert [t.split for t in result.targets] == ["fit", "holdout"]
    assert all(t.extraction_method == "automatic_vision_reviewed" for t in result.targets)
    assert len(list((tmp_path / "crops").glob("*.png"))) == 2


def test_repeated_figures_are_ambiguous_even_when_each_is_reviewed(pdf):
    result = extract_pdf_auto(pdf, "operations", requests()[:1], complete=lambda *a: json.dumps({"cells": [cell()]}),
                              review=lambda *a: True, strict=False)
    assert not result.targets and "ambiguous" in result.issues[-1]["reason"]


@pytest.mark.parametrize("bad", [dict(cell(), text="unreadable"), dict(cell(), bbox=[0, 0, 2, 2]),
                                dict(cell(), metric="unknown"), dict(cell(), split="fit")])
def test_invalid_model_rows_cannot_become_targets(pdf, bad):
    result = extract_pdf_auto(pdf, "operations", requests()[:1], pages=[1],
        complete=lambda *a: json.dumps({"cells": [bad]}), review=lambda *a: True, strict=False)
    assert not result.targets and result.issues


def test_page_budget_checked_before_model_and_missing_targets_fail_closed(pdf):
    with pytest.raises(ValueError, match="max_pages"):
        extract_pdf_auto(pdf, "operations", requests(), max_pages=1, complete=lambda *a: pytest.fail("must not call model"))
    result = extract_pdf_auto(pdf, "operations", requests(), complete=lambda *a: '{"cells": []}', strict=False)
    assert len(result.issues) == 2 and not result.targets
