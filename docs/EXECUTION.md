# Bounded execution and caching

## Independent metrics and coupled groups

```sh
reconloop run private/config.toml --parallel --max-workers 4 --out private/run
reconloop job private/config.toml --parallel --max-workers 4 --out private/jobs
reconloop batch private/a.toml private/b.toml --max-workers 2 --out private/jobs
```

`run_config(..., parallel=True)` dispatches independent report/metric pairs and
whole coupled groups to a bounded driver thread pool. Each work unit gets its own
runner and judge state; a coupled group is never split. Results and logs retain
deterministic order. Sequential execution remains the default. `max_workers` is
bounded between 1 and 32. Runners created by the batch API are closed after use
when they provide `close()`; closing a Spark runner does not stop shared compute.

Custom/model judges require `judge_factory(report, metric)` in parallel mode.
`runner_factory()` must likewise return an independent runner if provided.
Factories must be safe to call from worker threads. Logs are buffered per work
unit; a failed metric run raises before writing a combined success report.

`batch_run(configs, out_dir, max_workers=...)` runs configurations concurrently
with separate run directories/manifests, plus `batch.json`. A failed member does
not erase successful members. Nested config and metric pools are disabled to
keep the concurrency bound meaningful. This is driver fan-out: it does not
serialize Spark sessions onto executors or provision a distributed job service.

## Spark session context

Default parallel Spark runners use separate SQL sessions. Session configuration,
temporary views and registered UDFs are not automatically copied; use persistent
qualified tables, or a runner factory that sets up each session explicitly.
Spark's [new-session contract](https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.SparkSession.newSession.html)
describes which state is shared.

When driver thread properties or tags matter, supply `task_wrapper` according to
the installed PySpark runtime. For classic PySpark:

```python
from pyspark import inheritable_thread_target
from reconloop import run_config
from reconloop.runners.spark_runner import SparkRunner

records = run_config("private/config.toml", parallel=True, max_workers=4,
    runner_factory=lambda: SparkRunner(spark.newSession()),
    task_wrapper=inheritable_thread_target)
```

Spark Connect versions supporting the session form use
`task_wrapper=inheritable_thread_target(spark)`. The wrapper captures context
when wrapped; configure job properties first. Check the installed runtime's
[thread-wrapper API](https://spark.apache.org/docs/4.0.3/api/python/reference/api/pyspark.inheritable_thread_target.html).
Actual overlap depends on scheduler resources and data/query cost. No fixed
speedup is claimed, and live cluster scheduling needs deployment validation.

## Async model completions

```python
from reconloop.judge import AsyncLLMJudge

records = run_config("private/config.toml", parallel=True,
    judge_factory=lambda report, metric: AsyncLLMJudge(complete_async))
```

`complete_async(prompt)` is an async function returning the same JSON as
`LLMJudge`. Separate worker loops let one metric await a model while another
executes SQL. Each callback needs its own appropriate client/state, timeout,
retry and rate-limit policy. The synchronous facade cannot run on a thread with
an active asyncio event loop; use `await asyncio.to_thread(run_config, ...)`
there, or call `await judge.propose_async(state, runner)` directly.

## Fit-only precomputation

```sh
reconloop run private/config.toml --precompute --max-candidates 128 --max-queries 1000 --out private/run
```

Precomputation warms scalar queries for the Cartesian product of declared options
on fit dates only. Candidate and query upper bounds are checked before warming.
Bad alternatives are recorded as failures; the judge and guardrails still decide
which moves are defensible and accepted. Holdouts are never prefetched. The
coupled solver already performs bounded fit enumeration, so this option only
warms independent metrics. It can reduce later query round trips but may do more
total work than needed; it is opt-in and does not batch arbitrary SQL into one scan.

## Persistent scalar results

```toml
[cache]
path = "query-results.sqlite"
namespace = "analytics-principal:spark:warehouse-a"
source_version = "immutable-snapshot-2026-01"
ttl_seconds = 86400
```

Exact SQL is keyed together with the explicit namespace and immutable source
version. Include the execution principal, backend and relevant session settings
in the namespace; change the source version whenever any input or definition
dependency changes. SQL results are finite scalars, never arbitrary objects.
Failed queries are not cached. Threads within one run collapse concurrent misses;
separate processes may both compute a first miss before publishing the same key.

SQLite uses a local filesystem supporting file locks. Object-backed mounted
volumes are rejected for this cache. Keep the database private because values
can be sensitive. This is an opt-in local adapter, not a Delta/Redis service.
Expiry bounds persistent reuse, while the underlying runner may retain its normal
in-memory cache for a run. Pin data throughout each run. A version token cannot
detect an in-place data change under the same token.
