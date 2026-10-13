import json
from pathlib import Path

import pytest

from reconloop import Target
from reconloop.doctor import diagnose
from reconloop.extract.pdf import ExtractionResult
from reconloop.extract.sources import load_sources
from reconloop.storage import load_bundle, normalize_volume_path, publish_targets


@pytest.fixture
def extraction(tmp_path):
    source = tmp_path / "extraction"
    ExtractionResult(targets=[Target("t", "report", "metric", "2026-01-01", 12)]).write(source)
    (source / "crops").mkdir()
    (source / "crops" / "page-1.png").write_bytes(b"synthetic crop evidence")
    return source


def test_bundle_roundtrip_includes_crops_and_integrates_with_sources(extraction, tmp_path):
    bundle = publish_targets(extraction, tmp_path / "store", bundle_id="reviewed-v1")
    assert load_bundle(bundle)[0].value == 12
    manifest = json.loads((bundle / "READY.json").read_text())
    assert "crops/page-1.png" in manifest["files"]
    result = load_sources({"sources": [{"type": "bundle", "file": str(bundle)}]}, tmp_path)
    assert len(result.targets) == 1
    with pytest.raises(FileExistsError):
        publish_targets(extraction, tmp_path / "store", bundle_id="reviewed-v1")


def test_incomplete_extraction_and_changed_csv_cannot_publish(extraction, tmp_path):
    document = json.loads((extraction / "extraction.json").read_text())
    document["complete"] = False
    (extraction / "extraction.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="issues"):
        publish_targets(extraction, tmp_path / "store")
    document["complete"] = True
    document["targets"][0]["value"] = 99
    (extraction / "extraction.json").write_text(json.dumps(document))
    with pytest.raises(ValueError, match="differs"):
        publish_targets(extraction, tmp_path / "store")


def test_interrupted_and_tampered_bundles_are_unreadable(extraction, tmp_path):
    with pytest.raises(FileNotFoundError):
        load_bundle(extraction)
    bundle = publish_targets(extraction, tmp_path / "store")
    (bundle / "crops" / "page-1.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="integrity"):
        load_bundle(bundle)


def test_manifest_cannot_traverse_outside_bundle(extraction, tmp_path):
    bundle = publish_targets(extraction, tmp_path / "store")
    manifest = json.loads((bundle / "READY.json").read_text())
    manifest["files"]["../private.txt"] = "dummy"
    (bundle / "READY.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="file path"):
        load_bundle(bundle)


@pytest.mark.parametrize("path", ["dbfs:/FileStore/targets.csv", "/dbfs/Volumes/a/b/c/t", "/Volumes/a/b", "/Volumes/a/b/c/../x", "/Volumes/a/b/c//x", "/volumes/a/b/c/t"])
def test_volume_paths_reject_legacy_spellings_and_traversal(path):
    with pytest.raises(ValueError):
        normalize_volume_path(path)


def test_volume_scheme_normalizes_for_driver_python():
    assert normalize_volume_path("dbfs:/Volumes/catalog/schema/volume/targets") == "/Volumes/catalog/schema/volume/targets"
    assert normalize_volume_path("local/targets") is None


@pytest.mark.parametrize("platform,runtime", [("nt", "16.4"), ("posix", "13.2"), ("posix", "")])
def test_unsupported_volume_environments_fail_before_creating_paths(monkeypatch, platform, runtime):
    from types import SimpleNamespace
    import reconloop.storage as storage
    monkeypatch.setattr(storage, "os", SimpleNamespace(name=platform, environ={"DATABRICKS_RUNTIME_VERSION": runtime}))
    with pytest.raises(RuntimeError, match="require|needs"):
        storage.local_path("dbfs:/Volumes/catalog/schema/volume/targets")


def test_runner_uses_normalized_config_parent_for_relative_tables(monkeypatch, tmp_path):
    import reconloop.config as config
    (tmp_path / "facts.csv").write_text("value\n42\n", encoding="utf-8")
    original = config.local_path
    uri = "dbfs:/Volumes/catalog/schema/volume/config.toml"
    monkeypatch.setattr(config, "local_path", lambda value, base=None:
                        tmp_path / "config.toml" if value == uri else original(value, base))
    runner = config.build_runner({"runner": {"tables": {"facts": "facts.csv"}}}, uri)
    try:
        assert runner.run("SELECT value FROM facts") == 42
    finally:
        runner.con.close()


def test_doctor_reports_missing_dependency_and_storage_without_installing(monkeypatch, tmp_path):
    import reconloop.doctor as doctor
    original = doctor.importlib.import_module
    def missing(name):
        if name == "pdfplumber":
            raise ImportError("test missing dependency")
        return original(name)
    monkeypatch.setattr(doctor.importlib, "import_module", missing)
    result = diagnose(path=tmp_path, write_probe=True)
    assert result["ok"] is False
    assert any(c["name"] == "pdfplumber" and not c["ok"] and c["remedy"] for c in result["checks"])
    assert any(c["name"] == "storage" and c["ok"] for c in result["checks"])
    assert not list(tmp_path.iterdir())


def test_doctor_write_probe_requires_explicit_path():
    with pytest.raises(ValueError, match="requires"):
        diagnose(write_probe=True)
