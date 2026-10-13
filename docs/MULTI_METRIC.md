# Reconciling multiple metrics

One run can reconcile many metrics across many reports. By default each
report/metric pair has independent parameters, tolerance, iterations, residuals
and holdout checks. Explicit coupled groups can enforce cross-metric identities
within a report. Figures can come from CSVs, reviewed bundles or configured PDFs.

## Three-KPI example

```sh
python examples/multi_metric/generate_data.py
reconloop run examples/multi_metric/config.toml --out out_multi
reconloop score out_multi examples/multi_metric/answers.json
```

This produces net sales (currency), orders (count), and return rate (fraction)
across five periods, including one holdout. The stated-rule judge recovers all
three definitions. `report.md` contains a dashboard summary and a separate audit
trail per KPI. Per-target rows retain extraction provenance.

Use repeatable selectors for a subset, with a fresh output directory:

```sh
reconloop run examples/multi_metric/config.toml --report retail_dashboard --metric orders --metric return_rate --out out_selected
```

Unknown selections, missing metric definitions, duplicate IDs within a pair,
pairs without fit targets and conflicting units raise errors before queries run.
The old behavior of silently skipping metrics without specs is removed. Incomplete
PDF extraction blocks loading the config even when selecting another metric;
review the source or use reviewed CSV inputs.

## Shared declarations, independent choices

Declare common parameters under `[param_groups.<group>.<parameter>]`, then list
the group names on each metric:

```toml
[param_groups.retail.stores]
hypothesis = "universe"
default = "all"
[param_groups.retail.stores.options]
all = "TRUE"
comparable = "comparable"
[param_groups.retail.stores.keywords]
comparable = ["comparable"]

[metrics.orders]
param_groups = ["retail"]
unit = "count"
tolerance = 0.001
template = "SELECT SUM(orders) AS value FROM sales WHERE {stores}"
```

Declarations are copied into each spec, so changing one metric's options cannot
mutate another. A local `[metrics.<metric>.params.<parameter>]` replaces the whole
shared parameter. Duplicate names across selected groups are an error.
`[start.<metric>]` remains metric-specific.

Shared declarations do not force the same final choice across metrics. Declare a
`[coupled.<group>]` to require matching choices or component identities such as
share numerator = category volume. See [coupled reconciliation](COUPLED_METRICS.md)
for the bounded fit-only search, single holdout decision and audit evidence.
All members must have identical date/split coverage. Select the whole group or
none of it with `--metric`; partial group selections fail before queries run.
Bounded compound proposals within one metric are also supported; see
[versioned metrics](VERSIONED_METRICS.md).

## Agent work queue

This interactive API supports independent pairs. It rejects coupled configs;
use `run_config` or `reconloop run` for those groups so identities remain enforced.

```python
from reconloop.session import ReconSession
s = ReconSession.from_config("config.toml")
s.progress()                 # pending / active / final status for every pair
s.pending_pairs()            # unfinished (report, metric) pairs
print(s.open_next())          # optionally open_next("weekly_dashboard")
# Read status(), propose try_change(...), then close().
# Repeat until open_next() returns "ALL PAIRS CLOSED".
s.report("out_multi")
```

Close or defer the active pair before opening another. Closed pairs cannot be reopened in
the same session, preventing duplicate records from overwriting one another.
Start a new session for a rerun. Invalid targets now fail at session construction
rather than waiting for `open`.

Use `defer(reason, depends_on=[...])` to park a pair and `resume(report, metric)` to
continue with its full history and remaining budget. Deferred pairs have a separate
queue and never appear closed. Private checkpoints can persist active/deferred work
across process restarts. See [lifecycle and diagnostics](LIFECYCLE_DIAGNOSTICS.md).

For model judges with mutable conversations, use a fresh instance per pair:

```python
from reconloop import run_config
from reconloop.judge import LLMJudge
records = run_config("config.toml",
    judge_factory=lambda report, metric: LLMJudge(make_completion_callback(report, metric)))
```

`make_completion_callback` is application code. When `judge=` is passed instead,
that instance is reused across pairs as before; reset external conversation state
yourself. Do not pass both `judge` and `judge_factory`.
These judge arguments apply only to metrics outside declared coupled groups.
Parallel runs require a factory for custom or model judges. See
[bounded execution](EXECUTION.md) for runner isolation, async callbacks and caching.
