"""Load one or several CSV/PDF target sources from TOML configuration."""
from pathlib import Path

from .csv_targets import load_targets
from .pdf import ExtractionResult, extract_pdf


def load_sources(config: dict, base: Path, *, evidence_dir=None) -> ExtractionResult:
    result = ExtractionResult()
    sources = list(config.get("sources", []))
    if config.get("file"):
        sources.insert(0, {"type": "csv", "file": config["file"]})
    if not sources:
        raise ValueError("targets needs file or at least one [[targets.sources]] entry")
    for source in sources:
        path = Path(source["file"])
        path = path if path.is_absolute() else base / path
        kind = source.get("type", "csv")
        if kind == "csv":
            result.targets.extend(load_targets(path))
        elif kind == "pdf":
            options = {k: v for k, v in source.items() if k not in {"type", "file"}}
            extracted = extract_pdf(path, **options, strict=False, evidence_dir=evidence_dir)
            result.targets.extend(extracted.targets)
            result.evidence.extend(extracted.evidence)
            result.issues.extend(extracted.issues)
        else:
            raise ValueError(f"unknown target source type: {kind}")
    keys = [(t.report, t.metric, t.target_id) for t in result.targets]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate target IDs within a report/metric across source files")
    return result
