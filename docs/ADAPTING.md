# Adapting reconloop to your own data

Keep this repo generic. Put everything specific to your organisation in a separate, private place: an internal repo, a Databricks Git folder or a volume. The public package never needs to know your table names, metric definitions or tolerances.

```
reconloop/                 public, generic (this repo)
your-recon-config/         private
  config.toml              runner, targets file, policy, metric specs
  targets.csv              extracted from your trusted reports
  answers.json             optional: known answers, to score judges
  extract.py               your extraction for your report formats
```

## 1. Install in Databricks

- Clone this repo into a Git folder, then in a notebook: `%pip install -e /Workspace/Repos/<you>/reconloop`
- Or build a wheel (`python -m build`), put it in a Unity Catalog volume, and run `%pip install /Volumes/.../reconloop-0.1.0-py3-none-any.whl`

## 2. Write the metric specs

For each metric, start from the definition your current output uses (the `[start.<metric>]` block). Then list the options each parameter could legitimately take, the ones a stakeholder would recognise.

- One parameter per definitional choice: week boundary, universe, basket, gross/net, de-duplication, mapping.
- Tie each parameter to one reason from `hypotheses.CATALOG`. Extend the catalog if your domain needs another reason, but keep each entry something you could defend in a meeting.
- Add `keywords` per option: the words a report would use for that choice. The stated-rule judge and LLM judges both use them.
- Options are SQL fragments, and they can use `{as_of}`. Use three-part Unity Catalog names in the template.
- Set `tolerance` per metric to what the business would call a match.

## 3. Build the targets

One row per figure: `target_id, report, metric, as_of, value, unit, stated_rule, source_file, page, split, confidence`.

- Write `stated_rule` in the report's own words. It's the judge's strongest evidence.
- Mark one or two recent periods per report as `holdout`.
- See `EXTRACTION.md` for getting figures out of PDFs, decks and scans.

## 4. Run

- Batch with a baseline: `run_config("config.toml", judge=StatedRuleJudge(), out_dir=...)`
- Interactive with an agent: open `notebooks/reconcile_with_agent.py`, create `ReconSession.from_config(..., runner=SparkRunner(spark))`, and give the Assistant the prompt in the notebook plus `AGENT_GUIDE.md`.
- With a model endpoint: `LLMJudge(lambda p: call_your_endpoint(p))`

## 5. Review

- Read `report.md`. For anything marked `explained_residual` or `unresolved`, the likely causes are listed.
- Review `spec_changes_for_review.json`. Any option an agent added stays unverified until a person approves it and moves it into the spec.
- Keep the records. They're the evidence when someone asks why the numbers differ.

## 6. Handing off to others

Give them the public package, a private config with a few metrics already specified, a targets file and answers for those metrics, and this doc. They can bring their own extraction or judge, and `scoring.py` tells everyone whether it's better.
