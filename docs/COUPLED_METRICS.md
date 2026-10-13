# Coupled reconciliation

Some metrics cannot be validated independently. A share can match while both its
components are doubled, even though a separately reconciled volume is correct.
Coupled groups search declared choices together and enforce explicit identities.

```sh
python examples/coupled_metrics/generate_data.py
reconloop run examples/coupled_metrics/config.toml --out out_coupled
reconloop score out_coupled examples/coupled_metrics/answers.json
```

This fictional example has category volume, total volume and category share over
four periods, one held out. The initial share matches every report value with
duplicated components. The group corrects its grain and scores 3/3 definitions.

## Declare identities and shared choices

```toml
[coupled.dashboard]
metrics = ["category_volume", "total_volume", "category_share"]
max_candidates = 1000

[coupled.dashboard.parameters]
category_volume = ["grain"]
total_volume = ["grain"]
category_share = ["grain"]

[coupled.dashboard.shared]
grain = ["category_volume.grain", "total_volume.grain", "category_share.grain"]

[[coupled.dashboard.identities]]
name = "numerator_matches_volume"
left = "category_share.numerator"
right = "category_volume.value"
factor = 1.0
absolute_tolerance = 0.00000001
relative_tolerance = 0.000001

[[coupled.dashboard.identities]]
name = "denominator_matches_total"
left = "category_share.denominator"
right = "total_volume.value"
```

References end in `.value`, `.numerator` or `.denominator`; the latter two require
a ratio spec. The identity is `left = factor * right`. Tolerance is absolute plus
relative times the larger magnitude. Declare conversions explicitly; component
units are not inferred. Nonfinite arithmetic never satisfies an identity.
Shared declarations require the same **option name** across their parameter
references; ensure those names have consistent business meaning in each spec.

`parameters` limits which parameters can change. Omitted metrics search all their
parameters; an empty list freezes that metric at its configured start/defaults.
Other choices stay fixed. The Cartesian space must fit `max_candidates` before
any query executes (default 1000, maximum 100000). Large spaces need a narrower
declared search. All parameter changes remain within the option and hypothesis
catalog. Each member respects `max_move_size`, and total edits across the group
respect `max_changes`.

## Selection and holdouts

The solver evaluates candidates on fit periods only, enforcing all fit identities
and shared choices. It prefers more metrics within tolerance, then lower mean
fit variance, then fewer edits. Equal candidates retain deterministic declaration
order; a selected definition is not proof it is uniquely identifiable.

Only the best fit candidate reaches a holdout decision. Every member's holdout
must avoid worsening beyond policy, and all holdout identities must pass. A failure
rejects the whole group. There is no retry using holdout feedback. A joint move
must improve aggregate fit or repair a broken identity without worsening member
fits beyond the minimum-gain threshold. Every final member must also satisfy its
own tolerance and final holdout check; otherwise all group records are unresolved.

Each metric must have exactly one target per date with identical date/split
coverage across the group. Missing periods, mixed splits, overlapping groups,
unknown components and partial CLI metric selections are rejected. Groups run
separately per report; cross-report constraints are not supported.

## APIs and records

`run_config` and `reconloop job` discover `[coupled]` groups automatically. Per-metric
`judge` and `judge_factory` apply only to metrics outside those groups. Coupled
groups use the deterministic bounded solver, not independent model proposals.

```python
from reconloop.coupled import CoupledGroup, Identity, reconcile_coupled

group = CoupledGroup("share_check", ["volume", "share"],
    [Identity("numerator", "share.numerator", "volume.value")])
records = reconcile_coupled(group, specs, targets, runner)
```

JSON records contain the group, candidate fit scores, identity evidence, selected
choices, joint decision, rejection reason and final fit/holdout identity checks.
Markdown shows group checks alongside per-metric histories and ratio components.
The records contain holdout evidence and must not be fed back to a tuning judge.

`ReconSession.from_config` refuses coupled configs: its interactive single-metric
edits cannot preserve cross-metric invariants. Use `run_config` or
`reconcile_coupled` for those configurations. Existing independent sessions and
within-metric compound proposals continue to work unchanged.
