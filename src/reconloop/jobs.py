"""One auditable batch invocation for an external scheduler; no background service."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

from .config import run_config
from .extract.pdf import ExtractionError


def run_job(config, out_dir, **kwargs):
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    out = Path(out_dir) / run_id
    out.mkdir(parents=True, exist_ok=False)
    manifest = dict(run_id=run_id, started_at=started.isoformat(), status="running", output_dir=str(out))
    try:
        manifest["config_sha256"] = sha256(Path(config).read_bytes()).hexdigest()
        records = run_config(config, out_dir=out, **kwargs)
        counts = {s: sum(r.status == s for r in records) for s in ("reconciled", "explained_residual", "unresolved")}
        manifest.update(counts=counts, status="complete" if all(r.status == "reconciled" for r in records) else "needs_review")
    except ExtractionError as exc:
        exc.result.write(out / "extraction")
        manifest.update(status="needs_review", error=str(exc), phase="extraction")
    except Exception as exc:
        manifest.update(status="failed", error=str(exc))
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    (out / "run.json").write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    return manifest
