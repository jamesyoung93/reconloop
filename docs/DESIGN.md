# Design

## The problem

Someone rebuilds a metric from source tables. A trusted report already publishes that metric. The two disagree. Usually both are "right" under different definitions: the week boundary, which entities count, gross vs net, a restatement since publication. Finding which difference explains the gap is slow, manual and argued over, and it repeats for every metric and every report.

The obvious automation is tempting and wrong: let an agent tweak the query until the number matches. It will match, for reasons nobody can defend. That's overfitting, and it's worse than the gap it hides.

## The loop

1. **Targets.** Figures from the trusted report, each with an as-of date, the rule the report states, and a page reference. Some periods are marked holdout.
2. **Spec.** The metric as a SQL template with declared options per parameter. Each parameter is tied to one named reason from the hypothesis catalog. The options are the only moves allowed.
3. **Run and compare.** Code renders the SQL per period, runs it, and computes the relative variance per period. No model computes anything.
4. **Judge.** Its state contains fit periods, the stated rule, the gap shape and fit-only history, and it proposes a single or bounded compound change with named reasons and a rationale. Holdout values are omitted from that state, but Python judges still run in the same process with access to the runner. This is not a sandbox.
5. **Guardrails.** A change is accepted only if:
   - it names a catalog reason that matches the parameter's declared reason
   - it uses a declared option
   - it either reduces the fit variance or makes the gap at least 50% more consistent across periods without hurting the holdout
   - it doesn't worsen the holdout by more than a small tolerance
   - the number of accepted changes stays under a cap
6. **Stop and classify.** The loop stops when within tolerance or when nothing defensible is left. The residual is classified as:
   - `within_tolerance` → reconciled only if the holdout is also within tolerance (when present)
   - `level_shift` (a constant % gap) → explained residual, likely restatement, source difference or measure
   - `drift` → late data or restatement of recent periods
   - `noisy` → mapping, de-duplication or late data
7. **Record.** Every step is written as JSON plus Markdown, including rejected proposals and their reasons. A failed final holdout check makes the status `unresolved`. Residual causes are suggestions for review, not proven explanations.

## Why each guardrail exists

| Guardrail | Failure it prevents |
|---|---|
| Declared options only | Inventing filters ("exclude store 17") to hit a number |
| Named reason matching the parameter | Changes no stakeholder could explain |
| Holdout check | Fitting the visible periods, including their noise |
| Consistency rule | Keeping a wrong definition because it partly cancels a restatement |
| Pinning stated choices (stated-rule judge) | Undoing what the report says it does, to shave the fit number |
| Change cap | Long chains of small edits that add up to a fudge |
| `add_option` flagged for review | An agent's new SQL being trusted without a person signing it off |

## Judges

- **SearchJudge:** tries single changes and explicitly declared compound moves, keeping the largest fit reduction. It's a baseline, and it shows the trap.
- **StatedRuleJudge:** follows keywords in the stated rule, pins those choices, and searches the rest. Cheap and strong when reports state their rules.
- **LLMJudge:** a model reads the same state and proposes a single or compound change as JSON. Plug in any `complete(prompt) -> str`.
- **Agent in a session:** an assistant or a person calls `try_change` or `try_changes` directly and reads `status()`. Same guardrails.

Use `scoring.py` with an eval set of known answers to check that a model judge beats the stated-rule baseline. If it doesn't, use the baseline.

## Coupled metrics

Explicit [coupled groups](COUPLED_METRICS.md) already support identities and shared
choices across aligned metrics within one report. A bounded deterministic search
ranks declared combinations on fit periods, then checks one candidate against
holdouts without trying alternatives after rejection. Every member must finish
within tolerance and all identities must hold. These groups use their own batch
solver; independent metrics continue through the judges above.

## Planned extensions

- **Per-target tolerance and weighting:** big and small figures shouldn't count equally.
- **Restatement model:** estimate a restatement factor explicitly and report it, instead of only classifying the residual.
- **Notebook and pipeline metrics:** let a metric be a Python function instead of a SQL template, with the same option-space contract.
- **Cross-report consistency:** when two reports should share a definition, prefer judges that keep them consistent.

Compound moves, OCR evidence crops, ratio components and explicit vintage comparisons
are implemented. Vintage comparison detects changed results while holding other
choices fixed; it does not estimate a restatement factor or prove why data changed.
See [versioned metrics](VERSIONED_METRICS.md) and [extraction](EXTRACTION.md).
