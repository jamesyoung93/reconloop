# Reconciling multiple metrics

One run can reconcile many metrics across many reports. Each report/metric pair
has independent parameters, tolerance, iterations, residuals and holdout checks.
Figures can come from one CSV, several CSVs or configured PDF tiles.

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

Shared declarations do not force the same final choice across metrics. Coupled
optimization, cross-metric identities and multi-parameter proposals remain future
work. Review conflicting final choices in the report.

## Agent work queue

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

Close the active pair before opening another. Closed pairs cannot be reopened in
the same session, preventing duplicate records from overwriting one another.
Start a new session for a rerun. Invalid targets now fail at session construction
rather than waiting for `open`.

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
