"""Load a TOML config: data tables, metric specs, targets file, policy, judge."""
from __future__ import annotations

import tomllib
from pathlib import Path

from .extract import load_targets
from .metricspec import load_specs


def _rel(base: Path, p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (base / q)


def load_config(path: str | Path):
    path = Path(path)
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    specs = load_specs(cfg)
    targets = load_targets(_rel(base, cfg["targets"]["file"]))
    return cfg, specs, targets


def build_runner(cfg: dict, path: str | Path):
    base = Path(path).parent
    r = cfg.get("runner", {"type": "duckdb"})
    if r.get("type", "duckdb") == "duckdb":
        from .runners.duckdb_runner import DuckDBRunner
        return DuckDBRunner({k: _rel(base, v) for k, v in (r.get("tables") or {}).items()})
    if r["type"] == "spark":
        from pyspark.sql import SparkSession
        from .runners.spark_runner import SparkRunner
        return SparkRunner(SparkSession.builder.getOrCreate())
    raise ValueError(f"unknown runner type {r['type']}")


def run_config(path: str | Path, judge=None, out_dir: str | Path | None = None, log=print):
    """Run every report x metric automatically with a judge (default: SearchJudge)."""
    from .guardrails import Policy
    from .judge import SearchJudge
    from .loop import reconcile
    from .record import write
    cfg, specs, targets = load_config(path)
    runner = build_runner(cfg, path)
    policy = Policy(**cfg.get("policy", {}))
    judge = judge or SearchJudge()
    start = cfg.get("start", {})
    records = []
    for report, metric in sorted({(t.report, t.metric) for t in targets}):
        if metric not in specs:
            log(f"skip {report}/{metric}: no spec")
            continue
        ts = [t for t in targets if t.report == report and t.metric == metric]
        records.append(reconcile(specs[metric], ts, runner, judge, policy, start=start.get(metric), log=log))
    if out_dir:
        write(records, out_dir)
    return records
