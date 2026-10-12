# reconloop

Reconcile a metric you rebuilt from source data against figures in a trusted report, one explained change at a time, and keep a record of the work.

A judge (a rule-based baseline, an LLM, or an agent working in a notebook) proposes one definitional change at a time. Code runs the query and computes the variance. Guardrails decide whether the change is accepted. The loop stops when the fit numbers match or no defensible change remains, and records the holdout check and possible causes of any residual. Declared options constrain the search; the result still needs review.

```
trusted report ──extract──▶ targets ─┐
                                     ▼
metric spec (allowed choices) ──▶ run ──▶ compare ──▶ judge proposes ONE named change
                                     ▲                         │
                                     └──── guardrails: accept / reject ◀┘
                                                     │
                                         reconciliation record (show your work)
```

## Why the judge matters: the demo in one paragraph

The bundled demo is a fictional grocery chain. It has three "trusted reports", each built with a hidden definition: fiscal or calendar week, comparable or all stores, gross or net. One report's older weeks were also restated up 1.5% after publication.

A judge that only minimises the gap gets 2 of 3 right. On the restated report it keeps the wrong week definition, because that definition happens to soak up part of the restatement.

The stated-rule judge gets 3 of 3. It follows what the report says, reaches the right definition, and stops with an explained residual: an approximately 1.48% shortfall relative to targets restated upward by 1.5%, flagged as a possible restatement. Its holdout periods match within rounding tolerance.

Requires Python 3.11 or later. From a checkout of this repository:

```
pip install -e ".[dev]"
python examples/fictional_retail/generate_data.py
reconloop run examples/fictional_retail/config.toml --judge search      --out out_search
reconloop run examples/fictional_retail/config.toml --judge stated_rule --out out_rule
reconloop score out_rule examples/fictional_retail/answers.json
```

Open `out_rule/report.md` to see the step-by-step record.

## Ways to run it

| Mode | Judge | Use when |
|---|---|---|
| `reconloop run` | `SearchJudge` or `StatedRuleJudge` | Batch runs, baselines, CI |
| `reconcile(..., judge=LLMJudge(complete))` | Any model behind a `complete(prompt) -> str` function | You have an API or serving endpoint |
| `ReconSession` in a notebook | An agent (Genie or Assistant, Copilot) or a person | Interactive work. The agent follows `AGENT_GUIDE.md` and drives `try_change(...)` |

In every mode the model only proposes. Code computes, and guardrails decide.

## Core ideas

- **The metric spec is the governance.** Each metric is a SQL template plus declared options per parameter (week definition, universe, measure...). Each parameter is tied to a named reason from `hypotheses.CATALOG`. The judge can only move between declared options. A genuinely new option can be proposed with `add_option`, and it's flagged for human review.
- **An explained gap beats a small gap.** A change can be accepted because it makes the gap *consistent* across periods, even if the average gap grows, as long as the holdout doesn't get worse. That is how a restatement shows up as a clean level shift instead of being absorbed by a wrong definition.
- **Holdout values are omitted from judge state and session status.** Guardrails check whether a change worsens holdout variance, and final results outside holdout tolerance stay unresolved. This is an API convention, not isolation from Python code that can access the runner or files.
- **Every run leaves a record:** start and final definition, each change with its reason, accepted or rejected with why, the variance at each step, the residual pattern with likely causes, and the final SQL.

## Layout

```
src/reconloop/
  schema.py        Target, Change, Iteration, Residual, ReconRecord
  hypotheses.py    the catalog of legitimate reasons numbers differ
  metricspec.py    SQL template + declared options per parameter
  compare.py       variance and residual shape (level shift / drift / noisy)
  guardrails.py    acceptance rules
  loop.py          automatic loop with any judge
  session.py       step-by-step API for an agent or a person
  judge/           search, stated_rule, llm
  runners/         duckdb (local), spark (Databricks)
  extract/         csv targets, digital-PDF text (pdfplumber)
  record.py        JSON + Markdown records
  scoring.py       score a run against known answers
examples/fictional_retail/   demo data generator, config, answers
notebooks/                   Databricks notebook for agent-as-judge
AGENT_GUIDE.md               instructions for the agent
docs/                        design, adapting to your data, extraction
```

## Status

Version 0.1. One metric per report pair, one parameter change per step, SQL-template metrics. See `docs/DESIGN.md` for the planned extensions.

`explained_residual` means a pattern suggests possible causes; it does not establish that a restatement occurred. Agent-added options remain subject to human review, even if their numbers match.

## Data and execution boundaries

Use trusted SQL templates, option fragments and Python judges only. The runners execute SQL with the permissions of their DuckDB process or Spark session; reconloop is not a SQL sandbox. `add_option` makes SQL executable immediately and logs it for later review. Use a restricted data environment for agent-driven work.

Targets must have ISO dates, finite values and a `fit` or `holdout` split. Queries must return exactly one row and one finite column named `value`. A NULL or missing result is an error; use `COALESCE` explicitly when zero is the intended meaning. Relative variance against a zero target is undefined for a nonzero result and is written as `null` in JSON, with the reconciliation left unresolved.

An LLM completion callback receives report labels, stated rules and fit figures. Use an endpoint approved for that data. Keep real reports, business configurations, credentials and generated reconciliation records outside this public repository. All bundled demo inputs are generated locally from fictional data.

## Development

```sh
python -m pip install -e ".[dev]" build
python -m pytest -q
python -m build
```

CI runs the test suite and package build on Windows and Linux with Python 3.11 and 3.13. Spark's scalar-result contract is covered with a test double; a live Databricks workspace and external LLM endpoint are not required by the tests.

MIT licence. All demo data is fictional.
