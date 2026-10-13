"""Interactive session: an agent (Databricks Genie / Assistant, Copilot, or a person) acts as the judge.

The agent never computes variances. It reads `status()`, decides on ONE change with a
named reason, and calls `try_change(...)`. The session runs the numbers, applies the
guardrails, and records everything. `report()` writes the show-your-work record.

    from reconloop.session import ReconSession
    s = ReconSession.from_config("config.toml", runner=SparkRunner(spark))
    s.open("finance_report", "weekly_sales")
    print(s.status())
    s.try_change("window", "fiscal", "time_window", "Report says fiscal week.")
    ...
    s.close();  s.report("out/")
"""
from __future__ import annotations

from .compare import classify_residual, evaluate, score, split_targets, summarize_result
from .guardrails import Policy, check
from .hypotheses import CATALOG, RESIDUAL_HINTS
from .metricspec import MetricSpec
from .schema import Change, Iteration, ReconRecord, Target
from .batch import select_pairs


class ReconSession:
    def __init__(self, specs: dict[str, MetricSpec], targets: list[Target], runner, policy: Policy | None = None,
                 start: dict[str, dict[str, str]] | None = None):
        self.specs, self.targets, self.runner = specs, targets, runner
        self.policy = policy or Policy()
        self.start = start or {}
        self._pairs = [(r, m) for r, m, _ in select_pairs(specs, targets)]
        self.records: list[ReconRecord] = []
        self.spec_changes: list[dict] = []     # new options an agent added; need human review
        self._cur = None

    @classmethod
    def from_config(cls, path: str, runner=None):
        from .config import load_config, build_runner
        cfg, specs, targets = load_config(path)
        return cls(specs, targets, runner or build_runner(cfg, path), Policy(**cfg.get("policy", {})), cfg.get("start"))

    # ---------- discovery ----------
    def pairs(self) -> list[tuple[str, str]]:
        """All (report, metric) pairs that have targets and a spec."""
        return list(self._pairs)

    def pending_pairs(self, report: str | None = None) -> list[tuple[str, str]]:
        """Pairs without a closed record; the active pair stays pending until close()."""
        if report is not None and report not in {r for r, _ in self._pairs}:
            raise ValueError(f"unknown report: {report}")
        closed = {(r.report, r.metric) for r in self.records}
        return [(r, m) for r, m in self._pairs if (r, m) not in closed and (report is None or r == report)]

    def open_next(self, report: str | None = None) -> str:
        """Open the next unfinished KPI; refuses to discard an active pair."""
        if self._cur is not None:
            raise RuntimeError("close the current pair before opening another")
        pending = self.pending_pairs(report)
        return self.open(*pending[0]) if pending else "ALL PAIRS CLOSED"

    def progress(self) -> list[dict]:
        """Report-wide progress without exposing holdout values."""
        closed = {(r.report, r.metric): r.status for r in self.records}
        active = (self._cur["report"], self._cur["spec"].name) if self._cur else None
        return [dict(report=r, metric=m, status="active" if (r, m) == active else closed.get((r, m), "pending"))
                for r, m in self._pairs]

    # ---------- one reconciliation ----------
    def open(self, report: str, metric: str, start: dict[str, str] | None = None) -> str:
        if self._cur is not None:
            raise RuntimeError("close the current pair before opening another")
        if any((r.report, r.metric) == (report, metric) for r in self.records):
            raise ValueError("pair already closed; use a new session to rerun it")
        spec = self.specs[metric]
        ts = [t for t in self.targets if t.report == report and t.metric == metric]
        if not ts:
            raise ValueError(f"no targets for {report} / {metric}")
        fit, hold = split_targets(ts, metric)
        params = spec.initial_choices(self.start.get(metric) if start is None else start)
        rows, f, h = self._measure(spec, params, fit, hold)
        self._cur = dict(spec=spec, report=report, fit=fit, hold=hold, params=params, start=dict(params),
                         history=[Iteration(step=0, params=dict(params), fit_variance=f, holdout_variance=h, per_target=rows)],
                         tried=set())
        return self.status()

    def status(self) -> str:
        """Plain-text state for the agent: gap, shape, stated rule, allowed choices, history."""
        c = self._need()
        spec, last = c["spec"], self._last()
        fit_rows = [r for r in last.per_target if r["split"] == "fit"]
        pattern = classify_residual(fit_rows, spec.tolerance)
        lines = [f"RECONCILING {c['report']} / {spec.name}",
                 f"Stated rule in the report: {c['fit'][0].stated_rule or '(none given)'}",
                 f"Current definition: {spec.describe(c['params'])}",
                 f"Fit variance: {last.fit_variance:.2%} (tolerance {spec.tolerance:.2%})",
                 f"Gap shape: {pattern}" + (f" -> usually {', '.join(RESIDUAL_HINTS[pattern])}" if pattern in RESIDUAL_HINTS else ""),
                 "Per period (fit):"]
        lines += [f"  {r['as_of']}: gold {r['gold']:,.0f} | computed {r['computed']:,.0f} | {r['rel']:+.2%}" for r in fit_rows]
        lines.append("Allowed choices (param [reason]: options):")
        for k, p in spec.params.items():
            opts = ", ".join(o + ("*" if o == c["params"][k] else "") for o in p.options)
            lines.append(f"  {k} [{p.hypothesis}]: {opts}")
        lines.append("Already tried: " + (", ".join(f"{a}={b}" for a, b in sorted(c["tried"])) or "none"))
        lines.append("Reasons (hypothesis keys): " + ", ".join(CATALOG))
        lines.append("DONE: fit is within tolerance; close() records the final holdout check." if last.fit_variance <= spec.tolerance else
                     "NEXT: call try_change(param, option, hypothesis, rationale), or close() if nothing defensible is left.")
        return "\n".join(lines)

    def try_change(self, param: str, option: str, hypothesis: str, rationale: str, by: str = "agent") -> str:
        c = self._need()
        spec, last = c["spec"], self._last()
        change = Change(param=param, old=c["params"].get(param, ""), new=option, hypothesis=hypothesis,
                        rationale=rationale, proposed_by=by)
        if param not in spec.params or option not in spec.params[param].options:
            reason = "option is not declared in the metric spec (use add_option to propose a new one)"
            tf, th, rows = last.fit_variance, last.holdout_variance, last.per_target
            trial = dict(c["params"])
        else:
            trial = dict(c["params"], **{param: option})
            try:
                rows, tf, th = self._measure(spec, trial, c["fit"], c["hold"])
            except Exception as exc:
                tf, th, rows = last.fit_variance, last.holdout_variance, last.per_target
                reason = f"execution failed: {exc}"
            else:
                n_acc = sum(1 for i in c["history"] if i.accepted)
                reason = check(change, spec, last.fit_variance, tf, last.holdout_variance, th, n_acc, self.policy, last.per_target, rows)
        c["history"].append(Iteration(step=len(c["history"]), params=trial, fit_variance=tf, holdout_variance=th,
                                      per_target=rows, change=change, accepted=(reason == ""), reject_reason=reason))
        c["tried"].add((param, option))
        if reason:
            return f"REJECTED: {reason}\n\n" + self.status()
        c["params"] = trial
        return f"ACCEPTED: {param} {change.old} -> {option} ({hypothesis}). Fit now {tf:.2%}.\n\n" + self.status()

    def add_option(self, param: str, name: str, sql_fragment: str, rationale: str, by: str = "agent") -> str:
        """Propose a NEW definitional choice (real data engineering). Logged for human review.

        The fragment may use {as_of}. It becomes available to try_change immediately, but every
        record that uses it is flagged so a person signs it off before it is trusted.
        """
        c = self._need()
        p = c["spec"].params[param]
        if name in p.options:
            return f"option '{name}' already exists"
        p.options[name] = sql_fragment
        self.spec_changes.append(dict(metric=c["spec"].name, param=param, option=name, sql=sql_fragment,
                                      hypothesis=p.hypothesis, rationale=rationale, by=by, status="needs_review"))
        return f"Added option {param}={name} (needs human review). Now call try_change('{param}', '{name}', '{p.hypothesis}', ...)."

    def close(self) -> ReconRecord:
        c = self._need()
        spec, final = c["spec"], self._last()
        status, residual = summarize_result(final, spec.tolerance)
        new_opts = [s for s in self.spec_changes if s["metric"] == spec.name and c["params"].get(s["param"]) == s["option"]]
        if new_opts:
            residual.note += " Uses agent-added option(s) awaiting review: " + ", ".join(f"{s['param']}={s['option']}" for s in new_opts) + "."
        rec = ReconRecord(report=c["report"], metric=spec.name, start_params=c["start"], final_params=dict(c["params"]),
                          final_query=spec.render(c["params"], c["fit"][0].as_of), tolerance=spec.tolerance, status=status,
                          iterations=c["history"], residual=residual)
        self.records.append(rec)
        self._cur = None
        return rec

    def report(self, out_dir: str = "reconloop_out") -> str:
        from .record import write
        import json, os
        md = write(self.records, out_dir)
        if self.spec_changes:
            with open(os.path.join(out_dir, "spec_changes_for_review.json"), "w", encoding="utf-8") as f:
                json.dump(self.spec_changes, f, indent=2)
        return str(md)

    # ---------- internals ----------
    def _measure(self, spec, params, fit, hold):
        rf = evaluate(self.runner, spec, params, fit)
        rh = evaluate(self.runner, spec, params, hold) if hold else []
        return rf + rh, score(rf), (score(rh) if hold else None)

    def _last(self) -> Iteration:
        return next(i for i in reversed(self._cur["history"]) if i.accepted is not False)

    def _need(self):
        if self._cur is None:
            raise RuntimeError("call open(report, metric) first")
        return self._cur
