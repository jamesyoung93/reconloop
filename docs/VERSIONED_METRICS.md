# Versioned metrics and governed compound changes

`examples/versioned_metrics` is a complete fictional five-metric pipeline. It
contains full source snapshots, processing cycles, repeated category memberships,
revised amounts, late-added events and two territory assignment versions. Run:

```sh
python examples/versioned_metrics/generate_data.py
reconloop run examples/versioned_metrics/config.toml --out out_versioned
reconloop score out_versioned examples/versioned_metrics/answers.json
```

The expected result is 5/5 definitions with all holdouts within tolerance.
The data generator does not derive expected targets from the SQL under test.
All identifiers, figures and rules are fictional.

## Snapshot and cycle selection

Parameters may contain raw SQL fragments or structured options. A structured
`latest_partition` option orders the complete partition tuple lexicographically.
It does not combine a maximum date with a cycle from a different date.

```toml
[metrics.volume.params.data_vintage]
hypothesis = "data_vintage"
default = "publication"
[metrics.volume.params.data_vintage.options.publication]
type = "latest_partition"
source = "facts"
columns = ["event_id", "category", "amount", "snapshot_date", "cycle"]
order_by = ["snapshot_date", "cycle"]
cutoff_column = "snapshot_date"
cutoff = "2026-01-31"
```

Use the option in `WITH snapshot AS ({data_vintage}) ...`. `cutoff = "{as_of}"`
uses each target date, which is appropriate only when the report's data cutoff
really equals its measurement date. Prefer an explicit publication date for a
fixed historical report. With no `cutoff_column`, the latest available partition
is selected. `partition_by = ["feed"]` selects a snapshot independently per feed.
Null ordering keys are excluded; an empty selection must be handled explicitly
by the metric query or a quality check.

The source must contain **full snapshots**. Incremental or change-log feeds need
their own reconstruction logic. Freeze source tables or pin immutable versions
for a run: the runners cache query results, and reconloop does not create a
database transaction spanning external table updates. Three-part table identifiers
are accepted. Quoted/special identifiers require trusted raw SQL options.

## Category-aware deduplication

Filter category eligibility before deduplication. The choice between one row per
event and one row per event/category is a business definition, not a universal rule.

```toml
[metrics.volume.params.deduplication.options.event_category]
type = "deduplicate"
source = "scoped"
columns = ["event_id", "category", "amount", "row_id"]
keys = ["event_id", "category"]
order_by = ["row_id"]
```

The builder uses `ROW_NUMBER` with descending order, nulls last. Supply a stable,
unique tie-breaker in `order_by` and non-null business keys. Add a zero-valued
quality query when source uniqueness or completeness is uncertain; never rely on
arbitrary row order to choose conflicting duplicates. Internal columns beginning
`_recon_` are reserved. SQL builders are available directly in `reconloop.sql`.

## Dated territory assignments

Select the alignment version separately from the source data vintage, then use
an `alignment` option. It joins each fact's entity and event date to an assignment
with a half-open validity interval: `valid_from <= event_date < valid_to`.
A null end date means no upper bound. The output includes `territory`.

```toml
[metrics.volume.params.mapping.options.dated]
type = "alignment"
source = "deduped"
mapping = "selected_alignment"
columns = ["row_id", "event_id", "account", "event_date", "amount"]
entity_key = "account"
event_date = "event_date"
```

Optional mapping column names are `mapping_key`, `territory`, `valid_from`, and
`valid_to`. Project source columns without an existing `territory` name to avoid
collisions. The example adds two `[metrics.<name>.checks]` queries: one counts
unmatched assignments, the other finds multiplication of unique fact rows.
Every check must return one finite column named `value`, equal to zero. Failures
stop a baseline evaluation or reject a candidate. The left join deliberately
retains unmatched facts so those checks can see them. The builder alone does
not guarantee unique mappings: keep the checks when adapting the example.

## Shares and ratios

Declare `ratio` instead of `template`:

```toml
[metrics.share]
unit = "fraction"
tolerance = 0.001
[metrics.share.ratio]
numerator = "SELECT SUM(amount) AS value FROM sales WHERE product = 'Focus'"
denominator = "SELECT SUM(amount) AS value FROM sales"
scale = 1.0
zero_denominator = "error"
```

Both queries can use the same declared parameter fragments and `{as_of}`. Each
must satisfy the single-row scalar contract. Use `scale = 100.0` and a matching
target unit for percentage points. The default zero denominator raises an error;
`zero_denominator = "zero"` is an explicit business choice. Null or nonfinite
components remain errors. JSON stores component values and their queries in every
evaluation; Markdown includes final components for every period and split.

A share can match with both components incorrectly doubled. The example starts
ratio metrics with an established category grain rather than pretending a ratio
alone can identify it. Use count metrics, source checks and component inspection
to validate that grain. Constraints are optional and explicit: declare a
[coupled group](COUPLED_METRICS.md) to enforce identities between components and
independently targeted volumes. The coupled example demonstrates that repair.

## Compound proposals

Declare a bounded candidate for `SearchJudge` or its stated-rule fallback:

```toml
[metrics.volume.moves.regional_population]
options = { alignment_vintage = "published", territory_filter = "north" }
rationale = "The territory population depends on its assignment version."
[policy]
max_move_size = 3
max_changes = 8
```

Deterministic search considers individual alternatives and these declared groups;
it does not enumerate the full Cartesian product. `LLMJudge` accepts a `changes`
array with per-edit `param`, `value`, `hypothesis`, `rationale`, plus a joint
`rationale`. Interactive agents call `try_changes` (see `AGENT_GUIDE.md`).
All options and hypothesis matches are validated before candidate execution.
The group is evaluated and committed atomically. Each parameter edit consumes
one unit of `max_changes`; no-op, duplicate, stale and oversized edits are rejected.
Holdouts remain excluded from judge state, and the normal acceptance checks apply
to the whole group. Rejected alternatives may be reconsidered after the current
definition changes; their earlier attempts remain in the permanent audit.
Compound changes operate within one metric. Use the separate
[coupled solver](COUPLED_METRICS.md) for joint choices across metrics.

## Explicit revision evidence

```sh
reconloop revisions examples/versioned_metrics/config.toml --metric total_volume --parameter data_vintage --before published --after refreshed --records out_versioned --out out_revisions
```

The command writes `revisions.json` and `revisions.md`. It reuses each record's
final choices and varies only the named vintage. Without `--records`, it uses
configured starts/defaults. Options must be distinct and already declared under
`data_vintage`, `alignment_vintage`, `restatement` or `late_data`.
The Python `compare_vintages` API also accepts a nonnegative absolute tolerance.
Zero-baseline relative change is null when undefined; absolute deltas remain.
Component revisions are flagged even if numerator and denominator changes cancel.

These diagnostics include all selected periods, including holdouts. Run them
after reconciliation; do not feed them back into a judge. Changed aggregates do
not distinguish late arrivals, corrections or deletions. Row-level lineage or
source change logs are needed to establish that cause. The example's total
volume deltas are 16, 32, 48 and 64 across its four periods.

## Scheduled batch integration

```sh
reconloop job private/config.toml --out private/runs
```

Each invocation creates a new timestamp/UUID directory containing records,
Markdown and `run.json`: run ID, UTC start/end, config SHA-256, status and counts.
Exit codes are 0 for all reconciled, 3 for review (including explained residuals
or incomplete extraction), and 1 for execution failure. Failure manifests remain
available for a scheduler to surface. Review extraction JSON before reusing any
partial CSV. Source data/crops and output records stay in your private environment.
The package runs one batch; configure recurrence in your existing scheduler.

Model judges use `LLMJudge(complete)` or `run_config(..., judge_factory=...)` with
a caller-owned `complete(prompt) -> str` callback. Credentials, model selection,
request timeouts and serving deployment belong in that private integration. No
live model endpoint or live Spark cluster is included in the test suite; portable
SQL behavior is exercised locally and Spark's runner contract uses test doubles.
