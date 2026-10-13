import json
import os
from pathlib import Path
import runpy
import tomllib

import pytest

from reconloop.extract import ExtractionError, extract_pdf, load_targets
from reconloop.extract.pdf import TextResult, parse_number
from reconloop.extract.sources import load_sources


@pytest.mark.parametrize("raw,value", [("$1.25M", 1250000), ("2,400", 2400), ("12.5%", 0.125),
                                      ("($1,234.50)", -1234.5), ("−£20", -20), ("-$20", -20),
                                      ("1.5 K", 1500), ("0", 0), ("2B", 2e9)])
def test_dashboard_number_formats(raw, value):
    assert parse_number(raw) == pytest.approx(value)


@pytest.mark.parametrize("raw", ["1,2", "1.2.3", "O.50", "NaN", "(20", "20)", "--2", "-(20)"])
def test_bad_numbers_are_not_guessed(raw):
    with pytest.raises(ValueError):
        parse_number(raw)


def test_explicit_unit_conversions():
    assert parse_number("12.5%", percent="points") == 12.5
    assert parse_number("1.25", scale=1000) == 1250
    with pytest.raises(ValueError):
        parse_number("1", scale=float("inf"))


@pytest.fixture
def digital(tmp_path):
    pytest.importorskip("pdfplumber")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")

    def make(lines):
        path = tmp_path / "digital.pdf"
        c = canvas.Canvas(str(path), pagesize=(600, 400))
        for index, line in enumerate(lines):
            c.drawString(40, 350 - 30 * index, line)
        c.save()
        return path
    return make


def pattern(**kwargs):
    return dict(metric="sales", label="Sales", as_of=r"Week ending (\d{4}-\d{2}-\d{2})") | kwargs


def test_digital_text_never_calls_ocr_and_preserves_provenance(digital, tmp_path):
    path = digital(["Week ending 2026-01-08", "Sales", "$1.25M"])
    def fail(image):
        pytest.fail("digital text should not invoke OCR")
    result = extract_pdf(path, "dashboard", [pattern(unit="currency")], ocr_reader=fail)
    assert result.targets[0].value == 1250000
    assert result.targets[0].extraction_method == "text"
    assert result.evidence[0]["raw_value"] == "$1.25M"
    result.write(tmp_path / "out")
    assert load_targets(tmp_path / "out" / "targets.csv") == result.targets


def test_custom_value_above_label_and_custom_date(digital):
    path = digital(["As at 08/01/2026", "12.5%", "Return rate"])
    result = extract_pdf(path, "r", [pattern(label="Return rate", value_pattern=r"(?P<value>\d+\.\d+%)",
                         as_of=r"As at (\d+/\d+/\d+)", date_format="%d/%m/%Y")], ocr="never")
    assert result.targets[0].value == 0.125
    assert result.targets[0].as_of == "2026-01-08"


@pytest.mark.parametrize("lines", [["Sales 100", "Sales 200"], ["Profit 100"], ["Sales TBD", "Orders 200"]])
def test_missing_or_ambiguous_values_require_review(digital, lines):
    path = digital(["Week ending 2026-01-08"] + lines)
    with pytest.raises(ExtractionError) as exc:
        extract_pdf(path, "r", [pattern()], ocr="never")
    assert not exc.value.result.targets
    assert len(exc.value.result.issues) == 1


def test_auto_ocr_on_missing_value_even_when_page_has_digital_text(digital):
    path = digital(["Week ending 2026-01-08"])
    result = extract_pdf(path, "r", [pattern()], ocr_reader=lambda image: TextResult("Sales 1.2M", .95))
    assert result.targets[0].value == 1200000
    assert result.evidence[0]["method"] == "ocr"
    assert result.evidence[0]["date_method"] == "text"


def test_low_confidence_value_is_excluded_but_evidence_saved(digital, tmp_path):
    path = digital(["Week ending 2026-01-08"])
    result = extract_pdf(path, "r", [pattern()], strict=False,
                         ocr_reader=lambda image: TextResult("Sales 100", .99, [(0, 5, .99), (6, 9, .30)]))
    assert result.targets == []
    assert result.issues[0]["raw_value"] == "100"
    assert result.issues[0]["confidence"] == .30
    result.write(tmp_path / "out")
    assert json.loads((tmp_path / "out" / "extraction.json").read_text())["complete"] is False


def test_missing_date_is_not_fabricated(digital):
    path = digital(["Sales 100"])
    with pytest.raises(ExtractionError, match="date"):
        extract_pdf(path, "r", [pattern()], ocr="never")


def test_ambiguous_digital_text_cannot_be_overruled_by_incomplete_ocr(digital):
    path = digital(["Week ending 2026-01-08", "Sales 100", "Sales 200"])
    def fail(image):
        pytest.fail("ambiguous digital labels must stay unresolved")
    with pytest.raises(ExtractionError, match="found 2"):
        extract_pdf(path, "r", [pattern()], ocr_reader=fail)


def test_failed_ocr_match_retains_crop_for_review(digital, tmp_path):
    path = digital(["Week ending 2026-01-08"])
    result = extract_pdf(path, "r", [pattern()], strict=False, evidence_dir=tmp_path / "crops",
                         ocr_reader=lambda image: TextResult("Unreadable", .3))
    assert result.issues[0]["method"] == "ocr"
    assert (tmp_path / "crops" / result.issues[0]["crop"]).is_file()


@pytest.mark.parametrize("options", [{"pages": [0]}, {"pages": []}, {"bbox": [0, 0, 2, 1]}])
def test_invalid_page_and_region_configuration_is_rejected(digital, options):
    path = digital(["Week ending 2026-01-08", "Sales 100"])
    with pytest.raises(ValueError):
        extract_pdf(path, "r", [pattern(**options)], ocr="never")


def test_same_metric_multiple_patterns_get_distinct_ids(digital):
    path = digital(["Current 100", "Previous 90"])
    result = extract_pdf(path, "r", [pattern(label="Current", as_of_value="2026-01-08"),
                                     pattern(label="Previous", as_of_value="2026-01-01")], ocr="never")
    assert len({t.target_id for t in result.targets}) == 2


def test_tesseract_unavailable_has_actionable_error(monkeypatch):
    pytesseract = pytest.importorskip("pytesseract")
    Image = pytest.importorskip("PIL.Image")
    from reconloop.extract.pdf import tesseract_read
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "reconloop-no-such-tesseract")
    with Image.new("RGB", (100, 100), "white") as image:
        with pytest.raises(RuntimeError, match="not on PATH"):
            tesseract_read(image)


def test_real_ocr_extracts_three_metrics_from_hybrid_and_raster_pages(tmp_path):
    pytesseract = pytest.importorskip("pytesseract")
    try:
        pytesseract.get_tesseract_version()
    except (pytesseract.TesseractNotFoundError, OSError):
        if os.environ.get("RECONLOOP_REQUIRE_OCR") == "1":
            pytest.fail("This test job requires a working Tesseract executable")
        pytest.skip("Tesseract executable is not on PATH")
    pytest.importorskip("pdfplumber")
    pytest.importorskip("reportlab")
    root = Path(__file__).resolve().parents[1] / "examples" / "tableau_raster"
    runpy.run_path(str(root / "generate_pdf.py"))["generate"](tmp_path / "dashboard.pdf")
    config = tomllib.loads((root / "extract.toml").read_text())
    result = load_sources(config["targets"], tmp_path, evidence_dir=tmp_path / "crops")
    result.require_complete()
    assert len(result.targets) == 6
    got = {(t.as_of, t.metric): t.value for t in result.targets}
    assert got == {("2026-01-08", "net_sales"): 1250000, ("2026-01-08", "orders"): 2400,
                   ("2026-01-08", "return_rate"): .125, ("2026-01-15", "net_sales"): 1500000,
                   ("2026-01-15", "orders"): 2800, ("2026-01-15", "return_rate"): .1}
    assert all(t.extraction_method == "ocr" and t.confidence >= .8 for t in result.targets)
    assert all((tmp_path / "crops" / e["crop"]).is_file() for e in result.evidence)
    assert {e["date_method"] for e in result.evidence} == {"text", "ocr"}
