# Deferral, checkpoints and post-close diagnostics

## Park and resume a metric

```python
session.defer("Awaiting an independent conversion definition")
session.open_next()
session.close()
session.resume("operations", "sales")
```

Deferral preserves choices, accepted and rejected iterations, attempted moves,
agent-added options and the change budget. `pending_pairs()` excludes parked
pairs; `deferred_pairs()` lists them. `progress()` exposes status and reasons
without holdout figures. `open_next()` reports when only deferred pairs remain,
and `open()` cannot restart one accidentally. Close or defer the active pair
before opening or resuming another. Lifecycle events appear in the final record.

For a dependency, pass `depends_on=[("operations", "category_volume")]` to
`defer`. Dependencies must be other configured pairs and cannot form cycles.
`resume` requires those pairs to have reconciled. A dependency is a scheduling
condition; it does not enforce numeric identities. Use
[coupled reconciliation](COUPLED_METRICS.md) for those identities.

## Persist progress

```python
session.checkpoint("private/checkpoint-01.json", source_version="warehouse-snapshot-2026-01")
restored = ReconSession.from_config("private/config.toml")
restored.restore("private/checkpoint-01.json", source_version="warehouse-snapshot-2026-01")
```

Checkpoint files use JSON, retain full histories, and require a fresh filename.
Restore requires an empty session and exact matching specs, targets, start
choices, policy, diagnostics and source-version token. A content hash rejects
corruption before state is applied. If agent-added options changed the specs,
the restoring session must already contain those same reviewed declarations.

Pin immutable source data for the entire session and reuse that snapshot on
restore. A token records the caller's assertion; it does not freeze a warehouse
table. Checkpoints include holdout values and SQL history, so store them privately
and do not feed them into a tuning model. Hashes detect damage, not malicious
rewrites by someone who can replace the file. No pickle or code deserialization
is used. Runner connections and caches are recreated, not serialized.

`session.report()` writes closed records and `session_progress.json`; the report
states when pending or deferred pairs remain. A report is not a replacement for
a checkpoint when unfinished work must survive a process restart.

## Diagnose a residual after closing

Closed records automatically include `diagnostics.fit_ratio`. With at least three
distinct usable fit dates, code measures computed/target, its coefficient of
variation and individual deviations. Stable positive factors outside tolerance
are flagged as `constant`. Zero targets, nonpositive or nonfinite ratios are
excluded and listed. Sparse evidence is `insufficient`. Holdouts check the
fit-derived factor separately; they never estimate it.

A constant factor is consistent with a unit, measure, grain, coverage or
restatement difference. It does not identify which cause applies. No conversion
is applied and no status, choice, target or tolerance changes. Ratio metrics also
retain before/after numerator and denominator evidence, including when the share
itself is unchanged.

Optional declared diagnostics run after unresolved or explained-residual records:

```toml
[diagnostics.vintages.volume]
parameter = "data_vintage"
before = "published"
after = "refreshed"

[diagnostics.breakdowns.volume]
parameter = "segment"
max_queries = 1000
[diagnostics.breakdowns.volume.metrics]
north = "north_volume"
south = "south_volume"
```

Vintage checks hold the final definition fixed except for the named declared
vintage. Breakdown checks vary one declared parameter and compare each option
against its own independent reference metric targets in the same report. Those
reference targets must already be available; reconloop does not invent category
totals from an overall ratio. Separate fit factors can reveal differences across
categories that a pooled ratio hides. Neither diagnostic establishes causality.

Evidence is stored in JSON and summarized in Markdown. Query errors are retained
as diagnostic errors and do not rewrite the reconciliation outcome. Review them
before treating a diagnostic as complete. These outputs can include holdouts;
they must not be used to select new candidates against the same held-out data.
