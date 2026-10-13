import json

import pytest

from reconloop.extract.vision import VisionReader, extract_pdf_vision


def test_vision_self_confidence_cannot_bypass_independent_review():
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (200, 100), "white")
    reader = VisionReader(lambda png, prompt: '{"text":"Total: 25","confidence":1.0,"reviewed":true}')
    assert reader(image).confidence == 0
    assert reader.evidence[0]["reviewed"] is False
    assert reader.evidence[0]["text"] == "Total: 25"
    assert len(reader.evidence[0]["image_sha256"]) == 64
    image.close()


def test_vision_review_and_structured_reply_validation():
    Image = pytest.importorskip("PIL.Image")
    with Image.new("RGB", (200, 100), "white") as image:
        reader = VisionReader(lambda png, prompt: '{"text":"Total: 25"}', review=lambda image, text: text == "Total: 25")
        assert reader(image).confidence == 1
        with pytest.raises(RuntimeError, match="vision transcription failed"):
            VisionReader(lambda png, prompt: 'not JSON')(image)


def test_vision_pdf_requires_review_before_targets(tmp_path):
    pytest.importorskip("pdfplumber")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    path = tmp_path / "tile.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.drawString(50, 750, "Total: 25")
    pdf.save()
    patterns = [dict(metric="volume", label="Total", as_of_value="2026-01-01")]
    complete = lambda png, prompt: json.dumps({"text": "Total: 25"})
    pending = extract_pdf_vision(path, "report", patterns, complete=complete, strict=False)
    assert not pending.targets
    assert "requires independent review" in pending.issues[0]["reason"]
    assert any(e.get("text") == "Total: 25" for e in pending.evidence)
    approved = extract_pdf_vision(path, "report", patterns, complete=complete, review=lambda image, text: True)
    assert approved.targets[0].value == 25
    assert approved.targets[0].extraction_method == "vision_reviewed"
    with pytest.raises(ValueError, match="review gate"):
        extract_pdf_vision(path, "report", patterns, complete=complete, min_confidence=0)
