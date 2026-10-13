"""Load a TOML config: data tables, metric specs, targets file, policy, judge."""
from __future__ import annotations

import tomllib
from pathlib import Path

from .extract.sources import load_sources
from .batch import select_pairs
from .metricspec import load_specs
from .storage import local_path


def _rel(base: Path, p: str) -> Path:
    return local_path(p, base)


def load_config(path: str | Path):
    path = local_path(path)
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    specs = load_specs(cfg)
    targets = load_sources(cfg["targets"], base).require_complete()
    return cfg, specs, targets


def build_runner(cfg: dict, path: str | Path):
    base = local_path(path).parent
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
    from .coupled import load_groups, reconcile_coupled
    coupled = load_groups(cfg, specs)
    selected_pairs = {(r, m) for r, m, _ in groups}
    for group in coupled:
        for report in {r for r, _, _ in groups}:
            present = {m for r, m in selected_pairs if r == report} & set(group.metrics)
            if present and present != set(group.metrics):
                raise ValueError(f"select all members of coupled group {group.name!r} for report {report!r}")
    if judge is not None and judge_factory is not None:
        raise ValueError("provide judge or judge_factory, not both")
    runner = build_runner(cfg, path)
    policy = Policy(**cfg.get("policy", {}))
    judge = judge or SearchJudge()
    start = cfg.get("start", {})
    records = []
    completed = set()
    for group in coupled:
        for report in sorted({r for r, _, _ in groups}):
            if (report, group.metrics[0]) not in selected_pairs:
                continue
            ts = [t for t in targets if t.report == report and t.metric in group.metrics]
            records.extend(reconcile_coupled(group, specs, ts, runner, policy=policy, start=start, log=log))
            completed.update((report, m) for m in group.metrics)
    for report, metric, ts in groups:
        if (report, metric) in completed:
            continue
        pair_judge = judge_factory(report, metric) if judge_factory else judge
        records.append(reconcile(specs[metric], ts, runner, pair_judge, policy, start=start.get(metric), log=log))
    if out_dir:
        write(records, out_dir)
    return sorted(records, key=lambda r: (r.report, r.metric))
