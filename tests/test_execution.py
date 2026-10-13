import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Event

import pytest

from reconloop import MetricSpec, Param, Target, run_config
from reconloop.execution import precompute_fit
from reconloop.jobs import batch_run
from reconloop.judge import AsyncLLMJudge, LLMJudge
from reconloop.runners.duckdb_runner import DuckDBRunner
from reconloop.runners.persistent import CachedRunner, PersistentCache


@pytest.fixture
def config(tmp_path):
    (tmp_path / "targets.csv").write_text("target_id,report,metric,as_of,value,split\na,r,a,2026-01-01,10,fit\nb,r,b,2026-01-01,10,fit\nah,r,a,2049-01-01,10,holdout\nbh,r,b,2049-01-01,10,holdout\n")
    text = '[targets]\nfile="targets.csv"\n'
    for metric in ("a", "b"):
        text += f'''[metrics.{metric}]
template="SELECT {{measure}} AS value"
[metrics.{metric}.params.measure]
hypothesis="measure"
default="initial"
[metrics.{metric}.params.measure.options]
initial="5"
final="10"
'''
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_parallel_metrics_have_independent_judges_and_overlap_async_waits(config):
    barrier = Barrier(2)
    instances = []
    def factory(report, metric):
        async def complete(prompt):
            assert "2049-01-01" not in prompt
            barrier.wait(timeout=10)
            await asyncio.sleep(0)
            return json.dumps(dict(param="measure", value="final", hypothesis="measure", rationale="Known measure"))
        judge = AsyncLLMJudge(complete)
        instances.append(judge)
        return judge
    records = run_config(config, parallel=True, max_workers=2, judge_factory=factory, log=lambda *a: None)
    assert [r.metric for r in records] == ["a", "b"]
    assert all(r.status == "reconciled" for r in records)
    assert len({id(j) for j in instances}) == 2
    serial = run_config(config, log=lambda *a: None)
    assert [r.final_params for r in records] == [r.final_params for r in serial]


def test_parallel_rejects_shared_model_state_and_invalid_worker_budget(config):
    with pytest.raises(ValueError, match="judge_factory"):
        run_config(config, parallel=True, judge=LLMJudge(lambda p: "{}"))
    with pytest.raises(ValueError, match="max_workers"):
        run_config(config, parallel=True, max_workers=0)


def test_batch_fanout_retains_success_and_failure_manifests(config, tmp_path):
    result = batch_run([config, tmp_path / "missing.toml"], tmp_path / "jobs", max_workers=2, log=lambda *a: None)
    assert result["status"] == "failed"
    assert [r["status"] for r in result["runs"]] == ["complete", "failed"]
    assert all("output_dir" in r for r in result["runs"])
    with pytest.raises(ValueError, match="nested"):
        batch_run([config], tmp_path / "jobs", parallel=True)


def test_precompute_never_queries_holdouts_and_checks_budget_first():
    spec = MetricSpec("m", "SELECT {x} AS value -- {as_of}", {"x": Param("x", "measure", "one", {"one": "1", "two": "2"})})
    targets = [Target("f", "r", "m", "2026-01-01", 1), Target("h", "r", "m", "2049-01-01", 1, split="holdout")]
    runner = DuckDBRunner({})
    try:
        with pytest.raises(ValueError, match="budget"):
            precompute_fit(spec, targets, runner, max_candidates=1)
        assert not runner.cache
        result = precompute_fit(spec, targets, runner)
        assert result["candidates"] == 2 and len(runner.cache) == 2
        assert all("2049" not in sql for sql in runner.cache)
    finally:
        runner.close()


def test_precomputed_parallel_run_matches_serial_and_records_budget(config):
    before = run_config(config, log=lambda *a: None)
    after = run_config(config, parallel=True, precompute=True, log=lambda *a: None)
    assert [r.final_params for r in before] == [r.final_params for r in after]
    assert all(r.diagnostics["precompute"]["split"] == "fit" for r in after)


def test_persistent_cache_scoped_by_namespace_and_snapshot(tmp_path):
    path = tmp_path / "cache.sqlite"
    calls = []
    def execute(sql):
        calls.append(sql)
        return 42
    assert PersistentCache(path, namespace="test:duckdb", source_version="v1").get_or_run("SELECT 42 AS value", execute) == 42
    assert PersistentCache(path, namespace="test:duckdb", source_version="v1").get_or_run("SELECT 42 AS value", execute) == 42
    assert len(calls) == 1
    PersistentCache(path, namespace="test:duckdb", source_version="v2").get_or_run("SELECT 42 AS value", execute)
    PersistentCache(path, namespace="other:spark", source_version="v1").get_or_run("SELECT 42 AS value", execute)
    assert len(calls) == 3
    with pytest.raises(ValueError, match="source_version"):
        PersistentCache(path, namespace="test", source_version="")
    with pytest.raises(ValueError, match="object-backed"):
        PersistentCache("/Volumes/c/s/v/cache.sqlite", namespace="test", source_version="v1")


def test_cache_collapses_concurrent_misses_and_does_not_cache_errors(tmp_path):
    cache = PersistentCache(tmp_path / "cache.sqlite", namespace="test", source_version="v1")
    entered, release, calls = Event(), Event(), []
    def execute(sql):
        calls.append(sql)
        entered.set()
        assert release.wait(10)
        return 12
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(cache.get_or_run, "SELECT 12 AS value", execute)
        assert entered.wait(10)
        rest = [pool.submit(cache.get_or_run, "SELECT 12 AS value", execute) for _ in range(3)]
        release.set()
        assert [f.result() for f in [first, *rest]] == [12]*4
    assert len(calls) == 1
    with pytest.raises(ValueError):
        cache.get_or_run("invalid", lambda sql: float("nan"))
    assert cache.get_or_run("invalid", lambda sql: 5) == 5


def test_cache_ttl_expiry_forces_requery(monkeypatch, tmp_path):
    import reconloop.runners.persistent as persistent
    now = [100.0]
    monkeypatch.setattr(persistent.time, "time", lambda: now[0])
    cache = PersistentCache(tmp_path / "cache.sqlite", namespace="test", source_version="v1", ttl_seconds=10)
    assert cache.get_or_run("q", lambda sql: 1) == 1
    now[0] = 111
    assert cache.get_or_run("q", lambda sql: 2) == 2


def test_configured_cache_reused_after_runner_restart(config):
    with config.open("a") as stream:
        stream.write('\n[cache]\npath="results.sqlite"\nnamespace="test:duckdb"\nsource_version="fixture-v1"\n')
    run_config(config, log=lambda *a: None)
    class UnavailableRunner:
        def run(self, sql):
            pytest.fail("all exact queries should already be cached")
    records = run_config(config, runner_factory=UnavailableRunner, log=lambda *a: None)
    assert all(r.status == "reconciled" for r in records)


def test_parallel_spark_captures_driver_session_and_wraps_independent_workers(config, monkeypatch):
    import sys
    from threading import get_ident, local
    from types import SimpleNamespace
    context, driver, sessions = local(), get_ident(), []
    class Spark:
        def newSession(self):
            assert get_ident() != driver and context.wrapped
            child = Spark()
            sessions.append(child)
            return child
        def sql(self, query):
            return SimpleNamespace(columns=["value"], take=lambda n: [{"value": float(query.split()[1])}])
    base = Spark()
    def get_session():
        assert get_ident() == driver
        return base
    sql = SimpleNamespace(SparkSession=SimpleNamespace(builder=SimpleNamespace(getOrCreate=get_session)))
    monkeypatch.setitem(sys.modules, "pyspark", SimpleNamespace(sql=sql))
    monkeypatch.setitem(sys.modules, "pyspark.sql", sql)
    with config.open("a") as stream:
        stream.write('\n[runner]\ntype="spark"\n')
    def wrapper(function):
        def wrapped(unit):
            context.wrapped = True
            return function(unit)
        return wrapped
    records = run_config(config, parallel=True, task_wrapper=wrapper, log=lambda *a: None)
    assert all(r.status == "reconciled" for r in records)
    assert len(sessions) == 2 and len({id(s) for s in sessions}) == 2


def test_parallel_failure_closes_runners_without_success_artifact(config, tmp_path):
    closed = []
    class BrokenRunner:
        def run(self, sql):
            raise RuntimeError("unavailable source")
        def close(self):
            closed.append(self)
    with pytest.raises(RuntimeError, match="unavailable"):
        run_config(config, parallel=True, runner_factory=BrokenRunner, out_dir=tmp_path / "failed", log=lambda *a: None)
    assert closed and not (tmp_path / "failed").exists()
