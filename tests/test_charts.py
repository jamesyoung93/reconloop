import json
from dataclasses import asdict

import pytest

from reconloop import Target
from reconloop.extract.charts import extract_bars, measure_bar
from reconloop.extract.csv_targets import load_targets, write_targets

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")
COLOR = [40, 110, 190]


def picture(*, horizontal=False, negative=False):
    image = Image.new("RGB", (200, 200), "white")
    draw = ImageDraw.Draw(image)
    baseline = 100 if negative else 180
    if horizontal:
        draw.rectangle((20, 80, 139, 119), fill=tuple(COLOR))
    else:
        draw.rectangle((80, baseline if negative else 60, 119, 139 if negative else baseline-1), fill=tuple(COLOR))
    return image


def test_vertical_calibration_and_uncertainty():
    with picture() as image:
        result = measure_bar(image, bbox=[.425, .1, .575, .95], color=COLOR,
                             axis={"positions": [.9, .1], "values": [0, 80]}, pixel_uncertainty=2)
    assert result["value"] == pytest.approx(60)
    assert result["value_lower"] == 59 and result["value_upper"] == 61


def test_horizontal_and_negative_bars():
    with picture(horizontal=True) as image:
        r = measure_bar(image, bbox=[.05, .425, .9, .575], color=COLOR,
                        axis={"orientation": "horizontal", "positions": [.1, .9], "values": [0, 80]})
    assert r["value"] == 60
    with picture(negative=True) as image:
        r = measure_bar(image, bbox=[.425, .1, .575, .9], color=COLOR,
                        axis={"positions": [.1, .9], "values": [80, -80]})
    assert r["value"] == -40


@pytest.mark.parametrize("case", ["missing", "fragmented", "clipped", "unanchored", "log", "outside_ticks"])
def test_unsupported_or_ambiguous_charts_fail_closed(case):
    with picture() as image:
        draw = ImageDraw.Draw(image)
        bbox, axis = [.425, .1, .575, .95], {"positions": [.9, .1], "values": [0, 80]}
        if case == "missing":
            draw.rectangle((0, 0, 199, 199), fill="white")
        elif case == "fragmented":
            draw.rectangle((80, 90, 119, 99), fill="white")
        elif case == "clipped":
            bbox[1] = .3
        elif case == "unanchored":
            draw.rectangle((80, 160, 119, 199), fill="white")
        elif case == "log":
            axis["scale"] = "log"
        else:
            axis = {"positions": [.9, .5], "values": [0, 40]}
        with pytest.raises(ValueError):
            measure_bar(image, bbox=bbox, color=COLOR, axis=axis)


def test_pdf_bar_review_gate_and_bounds_survive_csv(tmp_path):
    pytest.importorskip("pdfplumber")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    image_reader = pytest.importorskip("reportlab.lib.utils").ImageReader
    path = tmp_path / "bars.pdf"
    with picture() as image:
        pdf = canvas.Canvas(str(path), pagesize=(200, 200))
        pdf.drawImage(image_reader(image), 0, 0, 200, 200)
        pdf.save()
    patterns = [dict(metric="volume", as_of="2026-01-01", bbox=[.425, .1, .575, .95], color=COLOR,
                     axis={"positions": [.9, .1], "values": [0, 80]})]
    pending = extract_bars(path, "report", patterns, dpi=144, strict=False, evidence_dir=tmp_path / "crops")
    assert not pending.targets and len(pending.issues) == 1
    assert pending.evidence[0]["value"] == pytest.approx(60, abs=.5)
    assert (tmp_path / "crops" / pending.evidence[0]["page_image"]).is_file()
    result = extract_bars(path, "report", patterns, dpi=144, review=lambda image, evidence: True)
    target = result.targets[0]
    assert target.value_lower <= 60 <= target.value_upper
    assert target.extraction_method == "chart_estimate_reviewed"
    write_targets(result.targets, tmp_path / "targets.csv")
    assert asdict(load_targets(tmp_path / "targets.csv")[0]) == asdict(target)


def test_invalid_estimate_interval_cannot_be_trusted():
    with pytest.raises(ValueError, match="bounds"):
        Target("t", "r", "m", "2026-01-01", 10, value_lower=11, value_upper=20)
