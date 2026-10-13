"""Load a TOML config: data tables, metric specs, targets file, policy, judge."""
from __future__ import annotations

import tomllib
from pathlib import Path

from .extract.sources import load_sources
from .batch import select_pairs
from .metricspec import load_specs


def _rel(base: Path, p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (base / q)


def load_config(path: str | Path):
    path = Path(path)
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    specs = load_specs(cfg)
    targets = load_sources(cfg["targets"], base).require_complete()
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


def run_config(path: str | Path, judge=None, out_dir: str | Path | None = None, log=print,
               *, reports: list[str] | None = None, metrics: list[str] | None = None,
               judge_factory=None):
    """Run every report x metric automatically with a judge (default: SearchJudge)."""
    from .guardrails import Policy
    from .judge import SearchJudge
    from .loop import reconcile
    from .record import write
    cfg, specs, targets = load_config(path)
    groups = select_pairs(specs, targets, reports=reports, metrics=metrics)
    if judge is not None and judge_factory is not None:
        raise ValueError("provide judge or judge_factory, not both")
    runner = build_runner(cfg, path)
    policy = Policy(**cfg.get("policy", {}))
    judge = judge or SearchJudge()
    start = cfg.get("start", {})
    records = []
    for report, metric, ts in groups:
        pair_judge = judge_factory(report, metric) if judge_factory else judge
        records.append(reconcile(specs[metric], ts, runner, pair_judge, policy, start=start.get(metric), log=log))
    if out_dir:
        write(records, out_dir)
    return records
